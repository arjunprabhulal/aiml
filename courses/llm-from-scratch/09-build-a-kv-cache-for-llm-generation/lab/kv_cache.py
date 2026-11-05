"""Generation with a key-value (KV) cache for the one-block model, standard library only.

Without a cache, every new token runs the whole model on every token so far.
With a cache, each step runs the model on the new token only: its query is
compared with the keys and values that earlier steps saved. Every other part of
the block works on one position at a time, so nothing else needs saving.
"""
import math
import random
from operator import mul

import generate as g
import model as m


class KVCache:
    """Keys and values of every position processed so far, for one sequence and one set of weights."""

    def __init__(self, params):
        self.params_id = id(params)
        self.keys, self.values = [], []

    def __len__(self):
        return len(self.keys)


def _row(x, w):
    cols = list(zip(*w))
    return [math.fsum(map(mul, x, col)) for col in cols]


def forward_step(p, cache, token_id, position):
    """Scores for the next token after appending one token at `position`, updating the cache."""
    if cache.params_id != id(p):
        raise ValueError("this cache was built with different parameters; start a new cache")
    if position != len(cache):
        raise ValueError(f"expected position {len(cache)}, got {position}: tokens must arrive in order")
    if position >= len(p["pos_emb"]):
        raise ValueError(f"position {position} is beyond the {len(p['pos_emb'])} positions the model has")
    if isinstance(token_id, bool) or not 0 <= token_id < len(p["tok_emb"]):
        raise ValueError(f"token ID {token_id!r} is outside the vocabulary")
    x0 = [a + b for a, b in zip(p["tok_emb"][token_id], p["pos_emb"][position])]
    h1 = m.layernorm_forward([x0], p["ln1_g"], p["ln1_b"])[0][0]
    q, k, v = _row(h1, p["Wq"]), _row(h1, p["Wk"]), _row(h1, p["Wv"])
    cache.keys.append(k)
    cache.values.append(v)
    scale = 1 / math.sqrt(len(q))
    weights = m.softmax_row([math.fsum(map(mul, q, kj)) * scale for kj in cache.keys])
    mixed = [math.fsum(map(mul, weights, col)) for col in zip(*cache.values)]
    x1 = [a + b for a, b in zip(x0, _row(mixed, p["Wo"]))]
    h2 = m.layernorm_forward([x1], p["ln2_g"], p["ln2_b"])[0][0]
    act = [v if v > 0 else 0.0 for v in (a + b for a, b in zip(_row(h2, p["W1"]), p["b1"]))]
    x2 = [a + (b + c) for a, b, c in zip(x1, _row(act, p["W2"]), p["b2"])]  # same order as model.forward
    hf = m.layernorm_forward([x2], p["lnf_g"], p["lnf_b"])[0][0]
    return [a + b for a, b in zip(_row(hf, p["W_out"]), p["b_out"])]


def generate_cached(p, tok, prompt, max_new_tokens=60, temperature=0.0, top_k=None, seed=0):
    """Same contract and output as generate.generate(), with one model row per step."""
    g.check_settings(temperature, top_k, len(p["tok_emb"]))
    ids = tok.encode(prompt)
    if not ids:
        raise ValueError("empty prompt: the model needs at least one token to continue")
    max_len = len(p["pos_emb"])
    if len(ids) > max_len:
        raise ValueError(f"prompt of {len(ids)} tokens is longer than the {max_len} positions the model has")
    cache = KVCache(p)
    for pos, token_id in enumerate(ids):  # prefill: one step per prompt token
        logits = forward_step(p, cache, token_id, pos)
    rng = random.Random(seed)
    steps, reason = [], "max_new_tokens"
    newline = tok.ids["\n"]
    for _ in range(max_new_tokens):
        if len(ids) == max_len:
            reason = "context full"
            break
        probs = g.next_token_probs(logits, temperature, top_k)
        choice = rng.choices(range(len(probs)), weights=probs)[0] if temperature > 0 else probs.index(1.0)
        ids.append(choice)
        steps.append({"token": tok.vocab[choice], "probability": round(probs[choice], 4)})
        if choice == newline:
            reason = "end of story"
            break
        if len(ids) < max_len:
            logits = forward_step(p, cache, choice, len(ids) - 1)
    return {"text": tok.decode(ids), "steps": steps, "stopped": reason}
