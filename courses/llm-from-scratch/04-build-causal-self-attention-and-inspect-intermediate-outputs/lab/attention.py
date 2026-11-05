"""Single-head causal self-attention with a hand-written backward pass.

Input x has shape (T, d_model): one row per position. The layer computes
  Q = x Wq, K = x Wk, V = x Wv                  each (T, d_head)
  S = Q K^T / sqrt(d_head)                       (T, T) scores
  S[i][j] = -inf for j > i                        the causal mask
  A = softmax of each row of S                    (T, T) attention weights
  out = A V Wo                                    (T, d_model)
Python 3.10+, standard library only.
"""
import math
import random

MASK_MODES = ("causal", "none", "zero")


def shape(t):
    dims = []
    while isinstance(t, list):
        dims.append(len(t))
        t = t[0] if t else None
    return tuple(dims)


def matmul(a, b):
    (n, k), (k2, m) = shape(a), shape(b)
    if k != k2:
        raise ValueError(f"cannot multiply {shape(a)} by {shape(b)}: inner sizes {k} and {k2} differ")
    bt = transpose(b)
    return [[math.fsum(x * y for x, y in zip(row, col)) for col in bt] for row in a]


def transpose(a):
    return [list(r) for r in zip(*a)]


def init_attention(d_model, d_head, seed):
    rng = random.Random(seed)
    w = lambda r, c: [[round(rng.uniform(-0.5, 0.5), 2) for _ in range(c)] for _ in range(r)]
    return {"Wq": w(d_model, d_head), "Wk": w(d_model, d_head),
            "Wv": w(d_model, d_head), "Wo": w(d_head, d_model)}


def softmax_row(row):
    finite = [v for v in row if v != -math.inf]
    top = max(finite)
    exps = [0.0 if v == -math.inf else math.exp(v - top) for v in row]
    total = math.fsum(exps)
    return [e / total for e in exps]


def attention_forward(params, x, mask="causal"):
    """Return the output and every intermediate tensor."""
    if mask not in MASK_MODES:
        raise ValueError(f"mask must be one of {MASK_MODES}, got {mask!r}")
    if not x:
        raise ValueError("empty sequence: attention needs at least one position")
    d_model = len(params["Wq"])
    if any(len(row) != d_model for row in x):
        raise ValueError(f"each input row must have {d_model} numbers, got {sorted({len(r) for r in x})}")
    T, d_head = len(x), len(params["Wq"][0])
    q, k, v = matmul(x, params["Wq"]), matmul(x, params["Wk"]), matmul(x, params["Wv"])
    scale = 1 / math.sqrt(d_head)
    raw = [[s * scale for s in row] for row in matmul(q, transpose(k))]
    if mask == "causal":
        scores = [[raw[i][j] if j <= i else -math.inf for j in range(T)] for i in range(T)]
    elif mask == "zero":  # a common bug: zeroing future scores instead of excluding them
        scores = [[raw[i][j] if j <= i else 0.0 for j in range(T)] for i in range(T)]
    else:
        scores = raw
    weights = [softmax_row(row) for row in scores]
    mixed = matmul(weights, v)
    out = matmul(mixed, params["Wo"])
    return {"q": q, "k": k, "v": v, "scores": scores, "weights": weights, "mixed": mixed, "out": out}


def attention_backward(params, x, cache, d_out):
    """Gradients of a scalar loss, given d_out = dLoss/d(out), shape (T, d_model)."""
    scale = 1 / math.sqrt(len(params["Wq"][0]))
    d_wo = matmul(transpose(cache["mixed"]), d_out)
    d_mixed = matmul(d_out, transpose(params["Wo"]))
    d_weights = matmul(d_mixed, transpose(cache["v"]))
    d_v = matmul(transpose(cache["weights"]), d_mixed)
    # Softmax backward, row by row: dS = A * (dA - sum(dA * A)). Masked entries have A = 0, so dS = 0.
    d_scores = []
    for a_row, da_row in zip(cache["weights"], d_weights):
        dot = math.fsum(a * da for a, da in zip(a_row, da_row))
        d_scores.append([a * (da - dot) * scale for a, da in zip(a_row, da_row)])
    d_q = matmul(d_scores, cache["k"])
    d_k = matmul(transpose(d_scores), cache["q"])
    grads = {
        "Wq": matmul(transpose(x), d_q),
        "Wk": matmul(transpose(x), d_k),
        "Wv": matmul(transpose(x), d_v),
        "Wo": d_wo,
    }
    d_x = [[math.fsum(t) for t in zip(*rows)] for rows in zip(
        matmul(d_q, transpose(params["Wq"])), matmul(d_k, transpose(params["Wk"])),
        matmul(d_v, transpose(params["Wv"])))]
    return grads, d_x
