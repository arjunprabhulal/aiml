"""Run the recorded training job and score the result.

Run: python3 trace_train.py          (train, print the trace; about two minutes on a laptop CPU)
     python3 trace_train.py --write  (also rewrite training-trace.json, params.json and training-time.json)
     python3 trace_train.py --check  (exit 1 if training-trace.json or params.json differ)
training-time.json holds the wall-clock time of the --write run and is not compared,
because timings change from run to run.
"""
import json
import platform
import sys
import time
from pathlib import Path

import train as t
from bpe import Tokenizer

HERE = Path(__file__).parent
SWEEP_RATES, SWEEP_STEPS = (0.001, 0.01, 0.1), 60


def run():
    tok = Tokenizer.load(HERE / "tokenizer.json")
    text = (HERE / "corpus.txt").read_text()
    _, dev, test = t.split_stories(text)
    te = t.encode_all(tok, test, t.CONFIG["max_len"])
    start = time.perf_counter()
    p, history, dev_history = t.train(tok, text)
    seconds = time.perf_counter() - start
    sweep = []
    for lr in SWEEP_RATES:
        cfg = dict(t.CONFIG, learning_rate=lr, steps=SWEEP_STEPS, eval_every=SWEEP_STEPS)
        _, h, dh = t.train(tok, text, cfg)
        sweep.append({"learning_rate": lr, "steps": SWEEP_STEPS, "last_batch_loss": h[-1],
                      "dev_loss": dh[-1]["dev_loss"]})
    record = {
        "config": t.CONFIG,
        "split": {"train": 280, "dev": len(dev), "test": len(test)},
        "train_loss_by_step": history,
        "dev_loss": dev_history,
        "test_loss": round(t.mean_loss(p, te), 4),
        "color_recall_test": t.color_recall(p, tok, test),
        "most_common_color_baseline": t.most_common_color_recall(t.split_stories(text)[0], test),
        "parameter_checksum": t.checksum(p),
        "learning_rate_sweep": sweep,
    }
    timing = {"seconds_for_recorded_run": round(seconds, 1), "steps": t.CONFIG["steps"],
              "python": platform.python_version(), "machine": platform.machine(), "system": platform.system()}
    return record, p, timing


if __name__ == "__main__":
    record, params, timing = run()
    text = json.dumps(record, indent=1) + "\n"
    params_text = json.dumps(params) + "\n"
    if "--write" in sys.argv:
        (HERE / "training-trace.json").write_text(text)
        (HERE / "params.json").write_text(params_text)
        (HERE / "training-time.json").write_text(json.dumps(timing, indent=1) + "\n")
    elif "--check" in sys.argv:
        same = (HERE / "training-trace.json").read_text() == text and (HERE / "params.json").read_text() == params_text
        sys.exit(0 if same else "training-trace.json or params.json is out of date")
    else:
        print(text, end="")
