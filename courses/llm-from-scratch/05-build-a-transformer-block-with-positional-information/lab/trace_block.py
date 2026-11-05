"""Run the one-block model on story text and record shapes, normalization and the position test.

Run: python3 trace_block.py          (print the trace)
     python3 trace_block.py --write  (rewrite block-trace.json)
     python3 trace_block.py --check  (exit 1 if block-trace.json is out of date)
"""
import json
import math
import sys
from pathlib import Path

import model as m
from bpe import Tokenizer

HERE = Path(__file__).parent
SERIES = {"d": 16, "hidden": 64, "max_len": 64, "seed": 3}  # the size later builds train
TINY = {"d": 4, "hidden": 8, "max_len": 8, "seed": 3}        # small enough to check every gradient
ORDER_A, ORDER_B = "now mia gives the hat to leo.", "now leo gives the hat to mia."
EPS = 1e-6


def build(tok, cfg):
    return m.init_params(len(tok.vocab), cfg["d"], cfg["hidden"], cfg["max_len"], cfg["seed"])


def gradient_error(p, x, y):
    logits, cache = m.forward(p, x)
    _, d = m.loss_and_dlogits(logits, y)
    g = m.backward(p, cache, d)
    worst = 0.0
    for name, value in p.items():
        rows, grow = (value, g[name]) if isinstance(value[0], list) else ([value], [g[name]])
        for row, gr in zip(rows, grow):
            for j in range(len(row)):
                old = row[j]
                row[j] = old + EPS
                up = m.sequence_loss(p, x, y)
                row[j] = old - EPS
                down = m.sequence_loss(p, x, y)
                row[j] = old
                worst = max(worst, abs((up - down) / (2 * EPS) - gr[j]))
    return worst


def position_gaps(p, tok, use_positions):
    """Largest score difference at each position between the two sentences."""
    a, _ = m.forward(p, tok.encode(ORDER_A), use_positions)
    b, _ = m.forward(p, tok.encode(ORDER_B), use_positions)
    return [round(max(abs(x - y) for x, y in zip(ra, rb)), 4) for ra, rb in zip(a, b)]


def last_logits_gap(p, tok, use_positions):
    a, _ = m.forward(p, tok.encode(ORDER_A), use_positions)
    b, _ = m.forward(p, tok.encode(ORDER_B), use_positions)
    return max(abs(x - y) for x, y in zip(a[-1], b[-1]))


def trace():
    tok = Tokenizer.load(HERE / "tokenizer.json")
    story = (HERE / "corpus.txt").read_text().split("\n")[0] + "\n"
    ids = tok.encode(story)
    p = build(tok, SERIES)
    logits, cache = m.forward(p, ids[:-1])
    loss, _ = m.loss_and_dlogits(logits, ids[1:])
    h1 = m.layernorm_forward(cache["x0"], p["ln1_g"], p["ln1_b"])[0]
    tiny = build(tok, TINY)
    short = tok.encode("mia has a red ball.")
    return {
        "story": story,
        "story_tokens": len(ids),
        "series_config": SERIES,
        "vocab_size": len(tok.vocab),
        "parameter_count": m.count_params(p),
        "parameters_by_tensor": {k: list(m.shape(v)) for k, v in p.items()},
        "shapes": {"x0": list(m.shape(cache["x0"])), "attention_weights": list(m.shape(cache["att"]["weights"])),
                   "mlp_hidden": list(m.shape(cache["act"])), "logits": list(m.shape(logits))},
        "initial_loss": round(loss, 4),
        "uniform_loss": round(math.log(len(tok.vocab)), 4),
        "layernorm_row0": {
            "mean": round(math.fsum(h1[0]) / len(h1[0]), 6) + 0.0,
            "variance": round(math.fsum(v * v for v in h1[0]) / len(h1[0]), 4),
        },
        "order_test": {
            "a": ORDER_A, "b": ORDER_B,
            "tokens_a": tok.tokens(ORDER_A), "tokens_b": tok.tokens(ORDER_B),
            "last_logit_gap_without_positions": last_logits_gap(p, tok, False),
            "last_logit_gap_with_positions": round(last_logits_gap(p, tok, True), 6),
            "gaps_by_position_without_positions": position_gaps(p, tok, False),
        },
        "gradient_check": {
            "config": TINY,
            "parameters_checked": m.count_params(tiny),
            "max_error_rounded": round(gradient_error(tiny, short[:-1], short[1:]), 7),
        },
    }


if __name__ == "__main__":
    path = HERE / "block-trace.json"
    text = json.dumps(trace(), indent=2, ensure_ascii=False) + "\n"
    if "--write" in sys.argv:
        path.write_text(text)
    elif "--check" in sys.argv:
        sys.exit(0 if path.read_text() == text else "block-trace.json is out of date")
    else:
        print(text, end="")
