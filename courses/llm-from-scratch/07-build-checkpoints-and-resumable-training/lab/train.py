"""Train the one-block model on the story corpus with Adam, standard library only.

Each training example is one whole story: the model reads tokens 0..n-2 and
predicts tokens 1..n-1. A step averages the gradients of a batch of stories,
then Adam updates every parameter. Development loss is measured every
EVAL_EVERY steps; the test stories are scored once, at the end.
"""
import math
import random
from operator import mul

import model as m
from bpe import Tokenizer

CONFIG = {
    "d": 16, "hidden": 64, "max_len": 64, "init_seed": 3, "data_seed": 5,
    "batch": 8, "steps": 600, "learning_rate": 0.01, "beta1": 0.9, "beta2": 0.999,
    "adam_eps": 1e-8, "eval_every": 50,
}


def split_stories(text, train=280, dev=60):
    stories = [s + "\n" for s in text.split("\n") if s]
    if train + dev >= len(stories):
        raise ValueError(f"need more than {train + dev} stories, got {len(stories)}")
    return stories[:train], stories[train:train + dev], stories[train + dev:]


def encode_all(tok, stories, max_len):
    out = []
    for s in stories:
        ids = tok.encode(s)
        if len(ids) - 1 > max_len:
            raise ValueError(f"story of {len(ids)} tokens does not fit {max_len} positions")
        out.append(ids)
    return out


def zeros_like(p):
    return {k: [[0.0] * len(v[0]) for _ in v] if isinstance(v[0], list) else [0.0] * len(v) for k, v in p.items()}


def accumulate(total, g, scale):
    for k, v in g.items():
        t = total[k]
        if isinstance(v[0], list):
            for tr, vr in zip(t, v):
                for j, x in enumerate(vr):
                    tr[j] += x * scale
        else:
            for j, x in enumerate(v):
                t[j] += x * scale


def batch_gradient(p, batch):
    """Mean loss and mean gradient over a batch of encoded stories."""
    total, losses = zeros_like(p), []
    for ids in batch:
        logits, cache = m.forward(p, ids[:-1])
        loss, d = m.loss_and_dlogits(logits, ids[1:])
        losses.append(loss)
        accumulate(total, m.backward(p, cache, d), 1.0 / len(batch))
    return math.fsum(losses) / len(losses), total


class Adam:
    """Adam with bias correction, as in Kingma and Ba (2015) and torch.optim.Adam without weight decay."""

    def __init__(self, p, lr, beta1, beta2, eps):
        if not (lr > 0 and math.isfinite(lr)):
            raise ValueError(f"learning rate must be a positive finite number, got {lr!r}")
        self.lr, self.b1, self.b2, self.eps, self.t = lr, beta1, beta2, eps, 0
        self.m, self.v = zeros_like(p), zeros_like(p)

    def step(self, p, g):
        self.t += 1
        c1, c2 = 1 - self.b1 ** self.t, 1 - self.b2 ** self.t
        for k in p:
            rows = (p[k], g[k], self.m[k], self.v[k])
            if not isinstance(p[k][0], list):
                rows = ([p[k]], [g[k]], [self.m[k]], [self.v[k]])
            for pr, gr, mr, vr in zip(*rows):
                for j, gj in enumerate(gr):
                    if not math.isfinite(gj):
                        raise ValueError(f"non-finite gradient in {k}")
                    mr[j] = self.b1 * mr[j] + (1 - self.b1) * gj
                    vr[j] = self.b2 * vr[j] + (1 - self.b2) * gj * gj
                    pr[j] -= self.lr * (mr[j] / c1) / (math.sqrt(vr[j] / c2) + self.eps)


def mean_loss(p, seqs):
    losses = [m.loss_and_dlogits(m.forward(p, s[:-1])[0], s[1:])[0] * (len(s) - 1) for s in seqs]
    return math.fsum(losses) / sum(len(s) - 1 for s in seqs)


def color_recall(p, tok, stories):
    """Predict the color in each story's last sentence from everything before it."""
    correct = 0
    for story in stories:
        color = story[story.index("now "):].split()[4]
        cut = story.rindex(" " + color)
        ids = tok.encode(story[:cut])
        logits, _ = m.forward(p, ids)
        guess = max(range(len(logits[-1])), key=lambda i: (logits[-1][i], -i))
        correct += tok.vocab[guess] == tok.tokens(" " + color)[0]
    return {"correct": correct, "total": len(stories)}


def most_common_color_recall(train_stories, stories):
    """A baseline that ignores the story: always guess the color seen most in training."""
    colors = [s.split()[3] for s in train_stories]
    top = max(sorted(set(colors)), key=colors.count)
    correct = sum(s[s.index("now "):].split()[4] == top for s in stories)
    return {"color": top, "correct": correct, "total": len(stories)}


def train(tok, text, cfg=CONFIG, log=None):
    train_s, dev_s, _ = split_stories(text)
    tr = encode_all(tok, train_s, cfg["max_len"])
    dv = encode_all(tok, dev_s, cfg["max_len"])
    p = m.init_params(len(tok.vocab), cfg["d"], cfg["hidden"], cfg["max_len"], cfg["init_seed"])
    opt = Adam(p, cfg["learning_rate"], cfg["beta1"], cfg["beta2"], cfg["adam_eps"])
    rng = random.Random(cfg["data_seed"])
    order, history, dev_history = [], [], []
    for step in range(1, cfg["steps"] + 1):
        if len(order) < cfg["batch"]:
            order += rng.sample(range(len(tr)), len(tr))  # a fresh shuffle each epoch
        batch = [tr[i] for i in order[:cfg["batch"]]]
        del order[:cfg["batch"]]
        loss, g = batch_gradient(p, batch)
        opt.step(p, g)
        history.append(round(loss, 4))
        if step % cfg["eval_every"] == 0 or step == cfg["steps"]:
            dev_history.append({"step": step, "dev_loss": round(mean_loss(p, dv), 4)})
            if log:
                log(step, loss, dev_history[-1]["dev_loss"])
    return p, history, dev_history


def checksum(p):
    """A short fingerprint of every parameter value, to compare two runs."""
    return round(math.fsum(math.fsum(map(mul, v, v)) if not isinstance(v[0], list)
                           else math.fsum(math.fsum(map(mul, r, r)) for r in v) for v in p.values()), 9)
