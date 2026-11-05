"""Score the three baselines and record the results.

Run: python3 trace_baseline.py          (print the trace)
     python3 trace_baseline.py --write  (rewrite baseline-trace.json)
     python3 trace_baseline.py --check  (exit 1 if baseline-trace.json is out of date)
"""
import json
import math
import random
import sys
from pathlib import Path

import baseline as b
from bpe import Tokenizer

HERE = Path(__file__).parent
K_GRID = (0.001, 0.01, 0.1, 1)
SAMPLE_SEED = 1


def scored(model, seqs):
    loss, n = b.cross_entropy(model, seqs)
    return {"loss": round(loss, 4), "perplexity": round(math.exp(loss), 2), "tokens": n}


def trace():
    tok = Tokenizer.load(HERE / "tokenizer.json")
    vocab = len(tok.vocab)
    train, dev, test = b.split_stories((HERE / "corpus.txt").read_text())
    tr, dv, te = (b.encode_stories(tok, s) for s in (train, dev, test))
    seen = {pair for s in tr for pair in zip(s, s[1:])}
    dev_bigram = {str(k): scored(b.Bigram(tr, vocab, k), dv) for k in K_GRID}
    best_k = min(K_GRID, key=lambda k: dev_bigram[str(k)]["loss"])
    models = {"uniform": b.Uniform(vocab), "unigram": b.Unigram(tr, vocab),
              "bigram": b.Bigram(tr, vocab, best_k)}
    bigram = models["bigram"]
    rng = random.Random(SAMPLE_SEED)
    return {
        "vocab_size": vocab,
        "split": {"train": len(train), "dev": len(dev), "test": len(test),
                  "rule": "stories in file order: first 280 train, next 60 dev, last 60 test"},
        "uniform_loss_formula": round(math.log(vocab), 4),
        "dev_pairs": {
            "total": sum(len(s) - 1 for s in dv),
            "unseen_in_training": sum(pair not in seen for s in dv for pair in zip(s, s[1:])),
        },
        "dev_bigram_by_k": dev_bigram,
        "chosen_k": best_k,
        "test": {name: scored(m, te) for name, m in models.items()},
        "recall": {"color": b.recall_check(tok, bigram, test, "color"),
                   "object": b.recall_check(tok, bigram, test, "object")},
        "top_after_the": [tok.vocab[i] for i in sorted(range(vocab), key=lambda i: -bigram.counts[tok.ids[" the"]][i])[:4]],
        "samples": {
            "seed": SAMPLE_SEED,
            "sampled": b.sample(bigram, tok, "mia has", 40, rng),
            "greedy": b.sample(bigram, tok, "mia has", 25, rng, greedy=True),
        },
    }


if __name__ == "__main__":
    path = HERE / "baseline-trace.json"
    text = json.dumps(trace(), indent=2, ensure_ascii=False) + "\n"
    if "--write" in sys.argv:
        path.write_text(text)
    elif "--check" in sys.argv:
        sys.exit(0 if path.read_text() == text else "baseline-trace.json is out of date")
    else:
        print(text, end="")
