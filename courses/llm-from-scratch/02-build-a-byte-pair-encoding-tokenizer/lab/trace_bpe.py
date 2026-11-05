"""Train the series tokenizer on corpus.txt and record what it learned.

Run: python3 trace_bpe.py          (print the trace)
     python3 trace_bpe.py --write  (rewrite bpe-trace.json and tokenizer.json)
     python3 trace_bpe.py --check  (exit 1 if either file is out of date)
"""
import json
import sys
from pathlib import Path

from bpe import Tokenizer

HERE = Path(__file__).parent
VOCAB_SIZE = 96
SWEEP = (40, 64, 96, 128)
SAMPLES = ["mia has a red ball.", "maya has a purple umbrella.", "café"]


def trace():
    text = (HERE / "corpus.txt").read_text()
    tok = Tokenizer.train(text, VOCAB_SIZE)
    ids = tok.encode(text)
    sweep = []
    for size in SWEEP:
        t = Tokenizer.train(text, size)
        n = len(t.encode(text))
        sweep.append({"requested": size, "vocab_size": len(t.vocab), "tokens": n,
                      "characters_per_token": round(len(text) / n, 3)})
    return {
        "corpus": {"characters": len(text), "stories": text.count("\n")},
        "alphabet": tok.alphabet,
        "base_vocab_size": 1 + len(tok.alphabet),
        "vocab_size": len(tok.vocab),
        "merge_count": len(tok.merges),
        "first_merges": tok.history[:12],
        "last_merges": tok.history[-5:],
        "corpus_tokens": len(ids),
        "characters_per_token": round(len(text) / len(ids), 3),
        "round_trip": tok.decode(ids) == text,
        "sweep": sweep,
        "samples": [{"text": s, "tokens": tok.tokens(s), "ids": tok.encode(s),
                     "decoded": tok.decode(tok.encode(s))} for s in SAMPLES],
    }, tok


if __name__ == "__main__":
    data, tok = trace()
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tok_text = json.dumps(tok.to_json(), indent=1, ensure_ascii=False) + "\n"
    trace_path, tok_path = HERE / "bpe-trace.json", HERE / "tokenizer.json"
    if "--write" in sys.argv:
        trace_path.write_text(text)
        tok_path.write_text(tok_text)
    elif "--check" in sys.argv:
        ok = trace_path.read_text() == text and tok_path.read_text() == tok_text
        sys.exit(0 if ok else "bpe-trace.json or tokenizer.json is out of date")
    else:
        print(text, end="")
