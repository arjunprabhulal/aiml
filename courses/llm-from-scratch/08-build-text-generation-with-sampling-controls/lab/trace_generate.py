"""Generate from the best checkpoint with several settings and record the results.

Run: python3 trace_generate.py          (print the trace)
     python3 trace_generate.py --write  (rewrite generation-trace.json and generation-time.json)
     python3 trace_generate.py --check  (exit 1 if generation-trace.json differs)
generation-time.json holds the time of the --write run and is not compared.
The settings are compared on the development stories; the test stories are not used here.
"""
import json
import platform
import sys
import time
from pathlib import Path

import checkpoint as ck
import generate as g
import model as m
import train as t
from bpe import Tokenizer

HERE = Path(__file__).parent
SETTINGS = [
    ("greedy", {"temperature": 0.0}),
    ("temperature 0.5", {"temperature": 0.5}),
    ("temperature 1.0", {"temperature": 1.0}),
    ("temperature 1.5", {"temperature": 1.5}),
    ("temperature 1.0, top-k 3", {"temperature": 1.0, "top_k": 3}),
]
SEED_PROMPT = "zoe has a blue kite."
COLOR_PROMPT = "mia has a red ball. mia goes to the park. at the park, mia gives the ball to leo. now leo has the"


def top_choices(probs, tok, n=5):
    order = sorted(range(len(probs)), key=lambda i: (-probs[i], i))[:n]
    return [{"token": tok.vocab[i], "probability": round(probs[i], 4)} for i in order]


def trace():
    tok = Tokenizer.load(HERE / "tokenizer.json")
    best = ck.load(HERE / "best.json", t.CONFIG, ck.input_signature(tok, (HERE / "corpus.txt").read_text()))
    p = best["params"]
    _, dev, _ = t.split_stories((HERE / "corpus.txt").read_text())
    table = []
    for name, kw in SETTINGS:
        counts = {"well_formed": 0, "keeps_color_and_object": 0}
        stops = {"end of story": 0, "max_new_tokens": 0, "context full": 0}
        for i, story in enumerate(dev):
            first = story.split(". ")[0] + "."
            result = g.generate(p, tok, first, seed=i, **kw)
            check = g.follows_story(first, result["text"])
            counts = {k: counts[k] + check[k] for k in counts}
            stops[result["stopped"]] += 1
        table.append({"setting": name, **kw, "stories": len(dev), **counts, "stopped": stops})
    logits, _ = m.forward(p, tok.encode(COLOR_PROMPT))
    distributions = {str(temp): top_choices(g.next_token_probs(logits[-1], temp, None), tok)
                     for temp in (0.5, 1.0, 2.0)}
    # Two stories cut to 62 tokens: only two positions remain in the 64-row table.
    long_prompt = tok.decode(tok.encode(dev[0] + dev[1])[:62])
    seeds = {seed: g.generate(p, tok, SEED_PROMPT, temperature=1.0, seed=seed) for seed in (1, 2)}
    step = next(i for i, (a, b) in enumerate(zip(seeds[1]["steps"], seeds[2]["steps"])) if a != b)
    return {
        "checkpoint": {"step": best["step"], "dev_loss": best["dev_loss"]},
        "greedy_example": g.generate(p, tok, "mia has a red ball."),
        "unseen_words_example": g.generate(p, tok, "maya has a purple umbrella."),
        "seed_prompt": SEED_PROMPT,
        "seeds": [{"seed": seed, "text": g.generate(p, tok, SEED_PROMPT, temperature=1.0, seed=seed)["text"]}
                  for seed in (1, 2, 1)],
        "seed_divergence": {"first_different_step": step + 1,
                            "same_tokens_before": [s["token"] for s in seeds[1]["steps"][:step]],
                            **{f"seed_{k}": seeds[k]["steps"][step] for k in (1, 2)}},
        "color_prompt": COLOR_PROMPT,
        "next_token_at_color": distributions,
        "context_full_example": {"prompt_tokens": len(tok.encode(long_prompt)),
                                 **g.generate(p, tok, long_prompt, max_new_tokens=60)},
        "dev_story_table": table,
    }


if __name__ == "__main__":
    path = HERE / "generation-trace.json"
    start = time.perf_counter()
    text = json.dumps(trace(), indent=1, ensure_ascii=False) + "\n"
    timing = {"seconds_for_trace": round(time.perf_counter() - start, 1), "python": platform.python_version(),
              "machine": platform.machine(), "system": platform.system()}
    if "--write" in sys.argv:
        path.write_text(text)
        (HERE / "generation-time.json").write_text(json.dumps(timing, indent=1) + "\n")
    elif "--check" in sys.argv:
        sys.exit(0 if path.read_text() == text else "generation-trace.json is out of date")
    else:
        print(text, end="")
