"""A one-block transformer language model in plain Python, with a hand-written backward pass.

For a sequence of token IDs (length T) the forward pass computes
  x0 = token embedding + position embedding            (T, d)
  x1 = x0 + Attention(LayerNorm1(x0))                  residual around causal self-attention
  x2 = x1 + MLP(LayerNorm2(x1))                         residual around a two-layer ReLU network
  logits = LayerNormF(x2) W_out + b_out                 (T, V)
and the loss is the mean cross-entropy of each next token. Normalization comes
before each sublayer (pre-LN). Every float sum uses math.fsum, so results are
identical on every Python version. Python 3.10+, standard library only.
"""
import math
import random
from operator import mul

EPS = 1e-5  # added to the variance inside layer normalization


# ---- list helpers ---------------------------------------------------------------

def shape(t):
    dims = []
    while isinstance(t, list):
        dims.append(len(t))
        t = t[0] if t else None
    return tuple(dims)


def transpose(a):
    return [list(r) for r in zip(*a)]


def matmul(a, b):
    """(n, k) @ (k, m) -> (n, m)."""
    if len(a[0]) != len(b):
        raise ValueError(f"cannot multiply {shape(a)} by {shape(b)}: inner sizes {len(a[0])} and {len(b)} differ")
    bt = transpose(b)
    return [[math.fsum(map(mul, row, col)) for col in bt] for row in a]


def add(a, b):
    return [[x + y for x, y in zip(ra, rb)] for ra, rb in zip(a, b)]


def add_bias(a, bias):
    return [[x + y for x, y in zip(row, bias)] for row in a]


def col_sums(a):
    return [math.fsum(col) for col in zip(*a)]


def zeros(r, c):
    return [[0.0] * c for _ in range(r)]


# ---- parameters -----------------------------------------------------------------

def init_params(vocab, d, hidden, max_len, seed):
    """Small random weights from a fixed seed; layer-norm gains start at 1 and biases at 0."""
    rng = random.Random(seed)
    def mat(r, c, scale):
        return [[rng.gauss(0.0, scale) for _ in range(c)] for _ in range(r)]
    s = 0.02
    return {
        "tok_emb": mat(vocab, d, s), "pos_emb": mat(max_len, d, s),
        "ln1_g": [1.0] * d, "ln1_b": [0.0] * d,
        "Wq": mat(d, d, s), "Wk": mat(d, d, s), "Wv": mat(d, d, s), "Wo": mat(d, d, s),
        "ln2_g": [1.0] * d, "ln2_b": [0.0] * d,
        "W1": mat(d, hidden, s), "b1": [0.0] * hidden, "W2": mat(hidden, d, s), "b2": [0.0] * d,
        "lnf_g": [1.0] * d, "lnf_b": [0.0] * d,
        "W_out": mat(d, vocab, s), "b_out": [0.0] * vocab,
    }


def count_params(params):
    return sum(len(v) * (len(v[0]) if isinstance(v[0], list) else 1) for v in params.values())


# ---- layer normalization ----------------------------------------------------------

def layernorm_forward(x, g, b):
    out, cache = [], []
    for row in x:
        n = len(row)
        mu = math.fsum(row) / n
        var = math.fsum((v - mu) ** 2 for v in row) / n
        inv = 1.0 / math.sqrt(var + EPS)
        xhat = [(v - mu) * inv for v in row]
        out.append([gi * xi + bi for gi, xi, bi in zip(g, xhat, b)])
        cache.append((xhat, inv))
    return out, cache


def layernorm_backward(dy, g, cache):
    dx, rows_dg, rows_db = [], [], []
    for dyr, (xhat, inv) in zip(dy, cache):
        n = len(dyr)
        dxhat = [d * gi for d, gi in zip(dyr, g)]
        s1, s2 = math.fsum(dxhat), math.fsum(map(mul, dxhat, xhat))
        dx.append([inv / n * (n * d - s1 - xh * s2) for d, xh in zip(dxhat, xhat)])
        rows_dg.append(list(map(mul, dyr, xhat)))
        rows_db.append(dyr)
    dg, db = col_sums(rows_dg), col_sums(rows_db)
    return dx, dg, db


# ---- causal self-attention (single head, width d) ------------------------------------

def softmax_row(row):
    top = max(v for v in row if v != -math.inf)
    exps = [0.0 if v == -math.inf else math.exp(v - top) for v in row]
    total = math.fsum(exps)
    return [e / total for e in exps]


def attention_forward(p, x):
    T, d = len(x), len(p["Wq"][0])
    q, k, v = matmul(x, p["Wq"]), matmul(x, p["Wk"]), matmul(x, p["Wv"])
    scale = 1 / math.sqrt(d)
    weights = []
    for i in range(T):
        scores = [math.fsum(map(mul, q[i], k[j])) * scale if j <= i else -math.inf for j in range(T)]
        weights.append(softmax_row(scores))
    mixed = matmul(weights, v)
    out = matmul(mixed, p["Wo"])
    return out, {"x": x, "q": q, "k": k, "v": v, "weights": weights, "mixed": mixed}


def attention_backward(p, c, d_out):
    scale = 1 / math.sqrt(len(p["Wq"][0]))
    grads = {"Wo": matmul(transpose(c["mixed"]), d_out)}
    d_mixed = matmul(d_out, transpose(p["Wo"]))
    d_weights = matmul(d_mixed, transpose(c["v"]))
    d_v = matmul(transpose(c["weights"]), d_mixed)
    d_scores = []
    for a_row, da_row in zip(c["weights"], d_weights):
        dot = math.fsum(map(mul, a_row, da_row))
        d_scores.append([a * (da - dot) * scale for a, da in zip(a_row, da_row)])
    d_q = matmul(d_scores, c["k"])
    d_k = matmul(transpose(d_scores), c["q"])
    xt = transpose(c["x"])
    grads["Wq"], grads["Wk"], grads["Wv"] = matmul(xt, d_q), matmul(xt, d_k), matmul(xt, d_v)
    d_x = add(add(matmul(d_q, transpose(p["Wq"])), matmul(d_k, transpose(p["Wk"]))),
              matmul(d_v, transpose(p["Wv"])))
    return grads, d_x


# ---- the full model ---------------------------------------------------------------------

def check_ids(p, ids):
    vocab, max_len = len(p["tok_emb"]), len(p["pos_emb"])
    if not ids:
        raise ValueError("empty sequence")
    if len(ids) > max_len:
        raise ValueError(f"sequence of {len(ids)} tokens is longer than the {max_len} positions the model has")
    bad = [i for i in ids if not 0 <= i < vocab]
    if bad:
        raise ValueError(f"token IDs outside the vocabulary of size {vocab}: {bad[:5]}")


def forward(p, ids, use_positions=True):
    """Return the logits (T, V) and everything backward() needs."""
    check_ids(p, ids)
    x0 = [list(p["tok_emb"][i]) for i in ids]
    if use_positions:
        x0 = add(x0, p["pos_emb"][:len(ids)])
    h1, ln1 = layernorm_forward(x0, p["ln1_g"], p["ln1_b"])
    a, att = attention_forward(p, h1)
    x1 = add(x0, a)
    h2, ln2 = layernorm_forward(x1, p["ln2_g"], p["ln2_b"])
    pre = add_bias(matmul(h2, p["W1"]), p["b1"])
    act = [[v if v > 0 else 0.0 for v in row] for row in pre]
    m = add_bias(matmul(act, p["W2"]), p["b2"])
    x2 = add(x1, m)
    hf, lnf = layernorm_forward(x2, p["lnf_g"], p["lnf_b"])
    logits = add_bias(matmul(hf, p["W_out"]), p["b_out"])
    cache = {"ids": ids, "use_positions": use_positions, "ln1": ln1, "att": att, "h2": h2, "ln2": ln2,
             "pre": pre, "act": act, "hf": hf, "lnf": lnf, "x0": x0, "x1": x1, "x2": x2}
    return logits, cache


def loss_and_dlogits(logits, targets):
    """Mean cross-entropy over positions and its gradient with respect to the logits."""
    if len(targets) != len(logits):
        raise ValueError(f"{len(logits)} positions but {len(targets)} targets")
    losses, d = [], []
    n = len(targets)
    for row, t in zip(logits, targets):
        probs = softmax_row(row)
        losses.append(-math.log(probs[t]))
        d.append([(pv - (1.0 if j == t else 0.0)) / n for j, pv in enumerate(probs)])
    return math.fsum(losses) / n, d


def backward(p, cache, d_logits):
    g = {}
    g["W_out"] = matmul(transpose(cache["hf"]), d_logits)
    g["b_out"] = col_sums(d_logits)
    d_hf = matmul(d_logits, transpose(p["W_out"]))
    d_x2, g["lnf_g"], g["lnf_b"] = layernorm_backward(d_hf, p["lnf_g"], cache["lnf"])
    # MLP branch; the residual passes d_x2 straight through to x1.
    g["W2"] = matmul(transpose(cache["act"]), d_x2)
    g["b2"] = col_sums(d_x2)
    d_act = matmul(d_x2, transpose(p["W2"]))
    d_pre = [[d if v > 0 else 0.0 for d, v in zip(dr, vr)] for dr, vr in zip(d_act, cache["pre"])]
    g["W1"] = matmul(transpose(cache["h2"]), d_pre)
    g["b1"] = col_sums(d_pre)
    d_h2 = matmul(d_pre, transpose(p["W1"]))
    d_x1_ln, g["ln2_g"], g["ln2_b"] = layernorm_backward(d_h2, p["ln2_g"], cache["ln2"])
    d_x1 = add(d_x2, d_x1_ln)
    # Attention branch; the residual passes d_x1 straight through to x0.
    att_g, d_h1 = attention_backward(p, cache["att"], d_x1)
    g.update(att_g)
    d_x0_ln, g["ln1_g"], g["ln1_b"] = layernorm_backward(d_h1, p["ln1_g"], cache["ln1"])
    d_x0 = add(d_x1, d_x0_ln)
    g["tok_emb"] = zeros(len(p["tok_emb"]), len(p["tok_emb"][0]))
    for i, row in zip(cache["ids"], d_x0):
        g["tok_emb"][i] = [a + b for a, b in zip(g["tok_emb"][i], row)]
    g["pos_emb"] = zeros(len(p["pos_emb"]), len(p["pos_emb"][0]))
    if cache["use_positions"]:
        for t, row in enumerate(d_x0):
            g["pos_emb"][t] = list(row)
    return g


def sequence_loss(p, ids, targets, use_positions=True):
    logits, _ = forward(p, ids, use_positions)
    return loss_and_dlogits(logits, targets)[0]
