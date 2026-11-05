"""Run causal self-attention on one tokenized sentence and record every intermediate value.

Run: python3 trace_attention.py          (print the trace)
     python3 trace_attention.py --write  (rewrite attention-trace.json)
     python3 trace_attention.py --check  (exit 1 if attention-trace.json is out of date)
"""
import json
import math
import random
import sys
from pathlib import Path

import attention as at
from bpe import Tokenizer

HERE = Path(__file__).parent
D_MODEL, D_HEAD, SEED = 4, 2, 11
SENTENCE, CHANGED = "mia has a red ball.", "mia has a red hat."
EPS = 1e-6


def embeddings(vocab_size, seed=SEED):
    rng = random.Random(seed + 1)
    return [[round(rng.uniform(-1, 1), 2) for _ in range(D_MODEL)] for _ in range(vocab_size)]


def readout(T, seed=SEED):
    rng = random.Random(seed + 2)
    return [[round(rng.uniform(-1, 1), 2) for _ in range(D_MODEL)] for _ in range(T)]


def loss(params, x, r, mask="causal"):
    out = at.attention_forward(params, x, mask)["out"]
    return math.fsum(o * w for orow, rrow in zip(out, r) for o, w in zip(orow, rrow))


def numeric_grad(params, x, r):
    grads = {}
    for name in params:
        g = []
        for i, row in enumerate(params[name]):
            g.append([])
            for j in range(len(row)):
                old = row[j]
                row[j] = old + EPS
                up = loss(params, x, r)
                row[j] = old - EPS
                down = loss(params, x, r)
                row[j] = old
                g[-1].append((up - down) / (2 * EPS))
        grads[name] = g
    return grads


def max_err(a, b):
    return max(abs(p - q) for name in a for ra, rb in zip(a[name], b[name]) for p, q in zip(ra, rb))


def r4(t):
    if isinstance(t, dict):
        return {k: r4(v) for k, v in t.items()}
    if isinstance(t, list):
        return [r4(v) for v in t]
    return None if t == -math.inf else round(t, 4)


def changed_rows(a, b):
    return [i for i, (ra, rb) in enumerate(zip(a, b)) if ra != rb]  # exact: any changed bit counts


def trace():
    tok = Tokenizer.load(HERE / "tokenizer.json")
    table = embeddings(len(tok.vocab))
    params = at.init_attention(D_MODEL, D_HEAD, SEED)
    ids, ids2 = tok.encode(SENTENCE), tok.encode(CHANGED)
    x, x2 = [table[i] for i in ids], [table[i] for i in ids2]
    cache = at.attention_forward(params, x)
    r = readout(len(x))
    grads, _ = at.attention_backward(params, x, cache, r)
    leak = {}
    for mode in at.MASK_MODES:
        a = at.attention_forward(params, x, mode)
        b = at.attention_forward(params, x2, mode)
        leak[mode] = {
            "rows_changed_by_the_edit": changed_rows(a["out"], b["out"]),
            "weight_on_future_row_0": round(math.fsum(a["weights"][0][1:]), 4),
        }
    return {
        "sentence": SENTENCE,
        "tokens": tok.tokens(SENTENCE),
        "ids": ids,
        "changed_sentence": CHANGED,
        "changed_tokens": tok.tokens(CHANGED),
        "d_model": D_MODEL,
        "d_head": D_HEAD,
        "seed": SEED,
        "shapes": {name: list(at.shape(cache[name])) for name in ("q", "k", "v", "scores", "weights", "mixed", "out")},
        "x": r4(x),
        "params": r4(params),
        "q": r4(cache["q"]), "k": r4(cache["k"]), "v": r4(cache["v"]),
        "scores": r4(cache["scores"]),
        "weights": r4(cache["weights"]),
        "out": r4(cache["out"]),
        "row_sums": [round(math.fsum(row), 6) for row in cache["weights"]],
        "masks": leak,
        "gradient_check": {
            "epsilon": EPS,
            "max_error_rounded": round(max_err(grads, numeric_grad(params, x, r)), 7),
        },
    }


if __name__ == "__main__":
    path = HERE / "attention-trace.json"
    text = json.dumps(trace(), indent=2, ensure_ascii=False) + "\n"
    if "--write" in sys.argv:
        path.write_text(text)
    elif "--check" in sys.argv:
        sys.exit(0 if path.read_text() == text else "attention-trace.json is out of date")
    else:
        print(text, end="")
