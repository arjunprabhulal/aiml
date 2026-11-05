"""Record uninterrupted, interrupted-and-resumed and incorrectly resumed training runs.

Run: python3 trace_checkpoints.py          (prints the trace; checkpoint-time.json records how long one run took)
     python3 trace_checkpoints.py --write  (also rewrite checkpoint-trace.json, best.json and checkpoint-time.json)
     python3 trace_checkpoints.py --check  (exit 1 if either file differs)
Checkpoints for each run go to a temporary folder that is deleted afterwards.
"""
import json
import platform
import time
import shutil
import sys
import tempfile
from pathlib import Path

import checkpoint as ck
import train as t
from bpe import Tokenizer

HERE = Path(__file__).parent
STOP_AT = 300


def scores(p, tok, test_seqs, test_stories):
    return {"test_loss": round(t.mean_loss(p, test_seqs), 4), "color_recall": t.color_recall(p, tok, test_stories),
            "params_sha256": ck.params_sha256(p), "checksum": t.checksum(p)}


def integrity_cases(folder, cfg):
    last = folder / "last.json"
    text = last.read_text()
    cases = {}
    bad = folder / "tampered.json"
    bad.write_text(text.replace('"step": ', '"step": 1', 1))
    truncated = folder / "truncated.json"
    truncated.write_text(text[: len(text) // 2])
    for name, path, config in (("one changed value", bad, cfg), ("truncated file", truncated, cfg),
                               ("different learning rate", last, dict(cfg, learning_rate=0.02))):
        try:
            ck.load(path, config)
            cases[name] = "accepted"
        except ValueError as error:
            cases[name] = str(error).replace(str(folder) + "/", "")
    return cases


def run():
    tok = Tokenizer.load(HERE / "tokenizer.json")
    text = (HERE / "corpus.txt").read_text()
    cfg = t.CONFIG
    _, _, test = t.split_stories(text)
    te = t.encode_all(tok, test, cfg["max_len"])
    work = Path(tempfile.mkdtemp())
    start = time.perf_counter()
    try:
        full, _, dev_history, best = ck.run(tok, text, cfg, work / "full")
        best_params = json.loads((work / "full" / "best.json").read_text())
        resumed = {}
        for name, flags in (("resumed", {}), ("resumed_without_optimizer_state", {"restore_optimizer": False}),
                            ("resumed_without_shuffle_state", {"restore_shuffle": False})):
            folder = work / name
            ck.run(tok, text, cfg, folder, stop_after=STOP_AT)
            p, _, dh, _ = ck.run(tok, text, cfg, folder, resume=True, **flags)
            resumed[name] = {"final_dev_loss": dh[-1]["dev_loss"], "params_sha256": ck.params_sha256(p)}
        record = {
            "config": cfg,
            "interrupted_at_step": STOP_AT,
            "uninterrupted": {"dev_loss": dev_history, "final": scores(full, tok, te, test)},
            "best_checkpoint": dict(best, **scores(best_params["params"], tok, te, test)),
            "resume_runs": resumed,
            "integrity": integrity_cases(work / "full", cfg),
        }
        timing = {"seconds_for_all_runs": round(time.perf_counter() - start, 1), "python": platform.python_version(),
                  "machine": platform.machine(), "system": platform.system()}
        return record, best_params, timing
    finally:
        shutil.rmtree(work)


if __name__ == "__main__":
    record, best, timing = run()
    text = json.dumps(record, indent=1) + "\n"
    best_text = json.dumps(best) + "\n"
    if "--write" in sys.argv:
        (HERE / "checkpoint-trace.json").write_text(text)
        (HERE / "best.json").write_text(best_text)
        (HERE / "checkpoint-time.json").write_text(json.dumps(timing, indent=1) + "\n")
    elif "--check" in sys.argv:
        same = (HERE / "checkpoint-trace.json").read_text() == text and (HERE / "best.json").read_text() == best_text
        sys.exit(0 if same else "checkpoint-trace.json or best.json is out of date")
    else:
        print(text, end="")
