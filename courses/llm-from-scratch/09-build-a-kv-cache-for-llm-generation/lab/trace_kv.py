"""Compare cached and uncached generation on the openings of the 60 test stories and record the results.

Run: python3 trace_kv.py          (print the trace; under a minute on a laptop CPU)
     python3 trace_kv.py --write  (rewrite kv-trace.json and kv-time.json)
     python3 trace_kv.py --check  (exit 1 if kv-trace.json differs)
kv-time.json holds wall-clock times from the --write run and is not compared,
because timings change from run to run and machine to machine.
"""
import json
import platform
import sys
import time
from pathlib import Path

import checkpoint as ck
import generate as g
import kv_cache as kv
import model as m
import train as t
from bpe import Tokenizer

HERE = Path(__file__).parent


def work(prompt_tokens, generated_tokens):
    """Rows the model processes and attention scores it computes, with and without a cache.

    Without a cache, the step that produces token number n runs the model on all n-1
    tokens before it. With a cache, every token is processed once.
    """
    lengths = range(prompt_tokens, prompt_tokens + generated_tokens)
    return {
        "uncached_rows": sum(lengths),
        "cached_rows": prompt_tokens + generated_tokens - 1 if generated_tokens else prompt_tokens,
        "uncached_scores": sum(n * (n + 1) // 2 for n in lengths),
        "cached_scores": sum(range(1, prompt_tokens + generated_tokens)),
    }


def run():
    tok = Tokenizer.load(HERE / "tokenizer.json")
    p = ck.load(HERE / "best.json", t.CONFIG, ck.input_signature(tok, (HERE / "corpus.txt").read_text()))["params"]
    _, _, test = t.split_stories((HERE / "corpus.txt").read_text())
    openings = [s.split(". ")[0] + "." for s in test]

    # 1. Every logit of a cached forward pass equals the matching row of the full forward pass.
    ids = tok.encode(test[0])[:-1]
    full, _ = m.forward(p, ids)
    cache = kv.KVCache(p)
    largest_gap = max(max(abs(a - b) for a, b in zip(kv.forward_step(p, cache, i, pos), full[pos]))
                      for pos, i in enumerate(ids))

    # 2. Greedy and sampled generation give the same text with and without the cache.
    same, totals, seconds = 0, {}, {}
    start = time.perf_counter()
    uncached = [g.generate(p, tok, o) for o in openings]
    seconds["uncached"] = time.perf_counter() - start
    start = time.perf_counter()
    cached = [kv.generate_cached(p, tok, o) for o in openings]
    seconds["cached"] = time.perf_counter() - start
    for o, a, b in zip(openings, uncached, cached):
        same += a == b
        for key, value in work(len(tok.encode(o)), len(a["steps"])).items():
            totals[key] = totals.get(key, 0) + value
    sampled_same = sum(g.generate(p, tok, o, temperature=1.0, seed=i) == kv.generate_cached(p, tok, o, temperature=1.0, seed=i)
                       for i, o in enumerate(openings))

    record = {
        "stories": len(openings),
        "largest_logit_gap_first_story": largest_gap,
        "positions_checked": len(ids),
        "greedy_identical": same,
        "sampled_identical": sampled_same,
        "generated_tokens": sum(len(a["steps"]) for a in uncached),
        "work": totals,
        "cache_floats_per_position": 2 * len(p["Wk"][0]),
        "cache_floats_full_context": 2 * len(p["Wk"][0]) * len(p["pos_emb"]),
    }
    timing = {"uncached_seconds": round(seconds["uncached"], 2), "cached_seconds": round(seconds["cached"], 2),
              "stories": len(openings), "python": platform.python_version(), "machine": platform.machine(),
              "system": platform.system()}
    return record, timing


if __name__ == "__main__":
    record, timing = run()
    text = json.dumps(record, indent=1) + "\n"
    if "--write" in sys.argv:
        (HERE / "kv-trace.json").write_text(text)
        (HERE / "kv-time.json").write_text(json.dumps(timing, indent=1) + "\n")
    elif "--check" in sys.argv:
        sys.exit(0 if (HERE / "kv-trace.json").read_text() == text else "kv-trace.json is out of date")
    else:
        print(text, end="")
