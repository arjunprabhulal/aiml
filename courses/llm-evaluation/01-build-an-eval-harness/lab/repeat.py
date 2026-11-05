"""Repeated trials: call triage() K times per case and report pass@k and pass^k for the label check."""
import json
from collections import Counter
from pathlib import Path

from harness import load_dataset
from triage import MODEL, Triage, triage

HERE = Path(__file__).parent
K = 5


def trials(cases) -> dict:
    rows = {}
    for case in cases:
        replies = [Triage.model_validate_json(triage(case.issue)) for _ in range(K)]
        rows[case.id] = {"expected": case.expected.label, "labels": [r.label for r in replies],
                         "priorities": [r.priority for r in replies]}
    return rows


def pass_rates(rows: dict) -> dict:
    right = {cid: [label == row["expected"] for label in row["labels"]] for cid, row in rows.items()}
    return {"pass@1": round(sum(r[0] for r in right.values()) / len(right), 3),
            f"pass@{K}": round(sum(any(r) for r in right.values()) / len(right), 3),  # right at least once
            f"pass^{K}": round(sum(all(r) for r in right.values()) / len(right), 3)}  # right every time


if __name__ == "__main__":
    rows = trials(load_dataset().cases)
    result = {"model": MODEL, "k": K, "cases": rows, "rates": pass_rates(rows)}
    (HERE / "runs" / "repeats.json").write_text(json.dumps(result, indent=2) + "\n")
    for cid, row in rows.items():
        changed = len(set(row["labels"])) > 1 or len(set(row["priorities"])) > 1
        print(f"{cid:<24}{dict(Counter(row['labels']))!s:<22}{dict(Counter(row['priorities']))!s:<22}"
              f"{'CHANGED' if changed else ''}")
    print(result["rates"])
