"""Fingerprint the outputs in a benchmark log, so two recordings can be compared by hash.

The digest covers every trial's case, trial number, output or error, and nothing
that describes the run (latency, start time, environment), so two recordings with
the same outputs have the same digest. recorded/recordings.json keeps the digest
of every recording made of the logs in this directory.
Python standard library only.
Run: python3 outputs_digest.py recorded/gemma.jsonl recorded/qwen.jsonl
"""
import hashlib
import sys

import bench
import harness


def digest(log_path):
    header, rows = bench.read_log(log_path)
    outcomes = sorted(([row["case_id"], row["trial"], row.get("output"), row.get("error")] for row in rows),
                      key=lambda item: (item[0], item[1]))
    return {"started_at": header["started_at"], "trials": len(outcomes),
            "outputs_sha256": hashlib.sha256(harness.canonical(outcomes).encode("utf-8")).hexdigest()}


if __name__ == "__main__":
    for path in sys.argv[1:]:
        print(path, digest(path))
