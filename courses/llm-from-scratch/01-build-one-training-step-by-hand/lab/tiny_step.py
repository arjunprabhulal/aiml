"""One training step for a tiny next-token model, written with Python lists.

The model maps each input token ID to an embedding row, multiplies that row by
an output weight matrix, adds a bias and turns the scores into probabilities.
Training compares the probabilities with the target token, computes gradients by
hand, checks them against finite differences and applies one SGD update.

Run:  python3 tiny_step.py           print the recorded trace as JSON
      python3 tiny_step.py --write   rewrite step-trace.json
      python3 tiny_step.py --check   exit 1 if step-trace.json is out of date
Python 3.10+, standard library only.
"""
import json
import math
import random
import sys
from pathlib import Path

VOCAB = ["red", "green", "stop", "go"]
INPUTS = ["red", "green", "red"]
TARGETS = ["stop", "go", "stop"]
EMBED_DIM = 2
SEED = 7
LEARNING_RATE = 0.5
EPSILON = 1e-5


# ---- tensors as nested lists -------------------------------------------------

def shape(t):
    """Return the shape of a rectangular nested list, e.g. (3, 2)."""
    dims = []
    while isinstance(t, list):
        dims.append(len(t))
        t = t[0] if t else None
    return tuple(dims)


def matmul(a, b):
    """(n, k) @ (k, m) -> (n, m). Rejects mismatched inner sizes."""
    (n, k), (k2, m) = shape(a), shape(b)
    if k != k2:
        raise ValueError(f"cannot multiply {shape(a)} by {shape(b)}: inner sizes {k} and {k2} differ")
    return [[math.fsum(a[i][p] * b[p][j] for p in range(k)) for j in range(m)] for i in range(n)]


def transpose(a):
    return [list(row) for row in zip(*a)]


# ---- model -------------------------------------------------------------------

def init_params(vocab_size=len(VOCAB), dim=EMBED_DIM, seed=SEED):
    """Small random starting values, rounded to two decimals so a reader can follow them."""
    rng = random.Random(seed)
    value = lambda: round(rng.uniform(-0.5, 0.5), 2)
    return {
        "embedding": [[value() for _ in range(dim)] for _ in range(vocab_size)],  # (V, d)
        "weights": [[value() for _ in range(vocab_size)] for _ in range(dim)],    # (d, V)
        "bias": [0.0] * vocab_size,                                               # (V,)
    }


def encode(tokens, vocab=VOCAB):
    index = {token: i for i, token in enumerate(vocab)}
    unknown = [t for t in tokens if t not in index]
    if unknown:
        raise ValueError(f"tokens not in the vocabulary: {unknown}")
    return [index[t] for t in tokens]


def check_batch(ids, targets, vocab_size):
    if not ids:
        raise ValueError("empty batch: a training step needs at least one example")
    if len(ids) != len(targets):
        raise ValueError(f"batch has {len(ids)} inputs but {len(targets)} targets")
    for i in list(ids) + list(targets):
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < vocab_size:
            raise ValueError(f"token ID {i} is outside the vocabulary of size {vocab_size}")


def softmax(row):
    top = max(row)  # subtracting the largest score keeps exp() from overflowing
    exps = [math.exp(v - top) for v in row]
    total = math.fsum(exps)
    return [e / total for e in exps]


def forward(params, ids, targets):
    """Return every intermediate value of the forward pass."""
    vocab_size = len(params["embedding"])
    check_batch(ids, targets, vocab_size)
    x = [list(params["embedding"][i]) for i in ids]                   # (B, d)
    scores = matmul(x, params["weights"])                             # (B, V)
    logits = [[s + b for s, b in zip(row, params["bias"])] for row in scores]
    probs = [softmax(row) for row in logits]                          # (B, V)
    losses = [-math.log(p[t]) for p, t in zip(probs, targets)]        # (B,)
    return {"x": x, "logits": logits, "probs": probs, "losses": losses,
            "loss": math.fsum(losses) / len(losses)}


def backward(params, ids, targets, cache, accumulate=True):
    """Gradients of the mean loss with respect to every parameter.

    accumulate=False reproduces a common bug: writing each example's embedding
    gradient into its row instead of adding it, so a repeated token ID keeps
    only its last example's contribution.
    """
    batch = len(ids)
    vocab_size = len(params["embedding"])
    d_logits = [[(p - (1.0 if j == t else 0.0)) / batch for j, p in enumerate(row)]
                for row, t in zip(cache["probs"], targets)]             # (B, V)
    d_weights = matmul(transpose(cache["x"]), d_logits)               # (d, V)
    d_bias = [math.fsum(col) for col in zip(*d_logits)]                     # (V,)
    d_x = matmul(d_logits, transpose(params["weights"]))              # (B, d)
    dim = len(d_x[0])
    d_embedding = [[0.0] * dim for _ in range(vocab_size)]            # (V, d)
    for i, row in zip(ids, d_x):
        if accumulate:
            d_embedding[i] = [a + g for a, g in zip(d_embedding[i], row)]
        else:
            d_embedding[i] = list(row)
    return {"embedding": d_embedding, "weights": d_weights, "bias": d_bias}


def loss_only(params, ids, targets):
    return forward(params, ids, targets)["loss"]


def numerical_gradients(params, ids, targets, eps=EPSILON):
    """Central differences: nudge one value up and down, compare the losses."""
    grads = {}
    for name, value in params.items():
        if isinstance(value[0], list):
            grads[name] = [[0.0] * len(value[0]) for _ in value]
            cells = [(r, c) for r in range(len(value)) for c in range(len(value[0]))]
        else:
            grads[name] = [0.0] * len(value)
            cells = [(c,) for c in range(len(value))]
        for cell in cells:
            original = _get(value, cell)
            _set(value, cell, original + eps)
            up = loss_only(params, ids, targets)
            _set(value, cell, original - eps)
            down = loss_only(params, ids, targets)
            _set(value, cell, original)
            _set(grads[name], cell, (up - down) / (2 * eps))
    return grads


def _get(t, cell):
    return t[cell[0]][cell[1]] if len(cell) == 2 else t[cell[0]]


def _set(t, cell, v):
    if len(cell) == 2:
        t[cell[0]][cell[1]] = v
    else:
        t[cell[0]] = v


def flat(t):
    return [v for row in t for v in row] if isinstance(t[0], list) else list(t)


def max_gradient_error(analytic, numeric):
    return max(abs(a - n) for name in analytic for a, n in zip(flat(analytic[name]), flat(numeric[name])))


def sgd_step(params, grads, learning_rate):
    if not (isinstance(learning_rate, (int, float)) and math.isfinite(learning_rate) and learning_rate > 0):
        raise ValueError(f"learning rate must be a positive finite number, got {learning_rate!r}")
    new = {}
    for name, value in params.items():
        g = grads[name]
        if isinstance(value[0], list):
            new[name] = [[v - learning_rate * gv for v, gv in zip(row, grow)] for row, grow in zip(value, g)]
        else:
            new[name] = [v - learning_rate * gv for v, gv in zip(value, g)]
    return new


def train_step(params, ids, targets, learning_rate=LEARNING_RATE):
    cache = forward(params, ids, targets)
    grads = backward(params, ids, targets, cache)
    updated = sgd_step(params, grads, learning_rate)
    return cache["loss"], grads, updated, loss_only(updated, ids, targets)


# ---- recorded trace ------------------------------------------------------------

def r6(t):
    if isinstance(t, dict):
        return {k: r6(v) for k, v in t.items()}
    if isinstance(t, list):
        return [r6(v) for v in t]
    return round(t, 6)


def trace():
    params = init_params()
    ids, targets = encode(INPUTS), encode(TARGETS)
    cache = forward(params, ids, targets)
    grads = backward(params, ids, targets, cache)
    numeric = numerical_gradients(params, ids, targets)
    overwrite = backward(params, ids, targets, cache, accumulate=False)
    loss_before, _, updated, loss_after = train_step(params, ids, targets)
    return {
        "vocab": VOCAB,
        "inputs": INPUTS,
        "targets": TARGETS,
        "input_ids": ids,
        "target_ids": targets,
        "seed": SEED,
        "learning_rate": LEARNING_RATE,
        "shapes": {
            "input_ids": list(shape(ids)),
            "embedding": list(shape(params["embedding"])),
            "x": list(shape(cache["x"])),
            "weights": list(shape(params["weights"])),
            "logits": list(shape(cache["logits"])),
            "bias": list(shape(params["bias"])),
        },
        "parameter_count": sum(len(flat(v)) for v in params.values()),
        "params_before": r6(params),
        "x": r6(cache["x"]),
        "logits": r6(cache["logits"]),
        "probs": r6(cache["probs"]),
        "losses": r6(cache["losses"]),
        "loss_before": round(loss_before, 6),
        "grads": r6(grads),
        "gradient_check": {
            "epsilon": EPSILON,
            # The exact error depends on floating-point rounding; its power of ten is stable.
            "max_error_power_of_ten": math.floor(math.log10(max_gradient_error(grads, numeric))),
            "max_error_overwrite_bug": round(max_gradient_error(overwrite, numeric), 6),
            "loss_after_overwrite_bug": round(loss_only(sgd_step(params, overwrite, LEARNING_RATE), ids, targets), 6),
        },
        "params_after": r6(updated),
        "loss_after": round(loss_after, 6),
        "learning_rate_sweep": [
            {"learning_rate": lr, "loss_after": round(train_step(params, ids, targets, lr)[3], 6)}
            for lr in (0.1, 0.5, 1, 2, 5, 10, 20)
        ],
        "large_learning_rate": {
            "learning_rate": 20,
            "loss_after": round(train_step(params, ids, targets, 20)[3], 6),
        },
    }


if __name__ == "__main__":
    path = Path(__file__).with_name("step-trace.json")
    text = json.dumps(trace(), indent=2) + "\n"
    if "--write" in sys.argv:
        path.write_text(text)
    elif "--check" in sys.argv:
        sys.exit(0 if path.read_text() == text else "step-trace.json is out of date")
    else:
        print(text, end="")
