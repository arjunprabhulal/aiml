"""Summarize the committed real local-inference record without rerunning a model."""

import json
import math
import statistics
from pathlib import Path


def summarize(samples):
    if not samples:
        raise ValueError("At least one completed generation is required")
    for sample in samples:
        values = [sample["ttft_ms"], sample["e2e_ms"], *sample["itl_ms"]]
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError("Timing values must be finite and nonnegative")
        if sample["generated_tokens"] != len(sample["generated_token_ids"]):
            raise ValueError("Token count mismatch")
        if sample["ttft_ms"] < 0 or sample["e2e_ms"] < sample["ttft_ms"]:
            raise ValueError("Invalid token timing")
        if len(sample["itl_ms"]) != max(0, sample["generated_tokens"] - 1):
            raise ValueError("Missing token intervals")
        if not math.isclose(
            math.fsum(sample["itl_ms"]),
            sample["e2e_ms"] - sample["ttft_ms"],
            abs_tol=0.002 * max(1, len(sample["itl_ms"])),
        ):
            raise ValueError("Intervals do not account for end-to-end timing")

    return {
        "samples": len(samples),
        "median_ttft_ms": round(statistics.median(x["ttft_ms"] for x in samples), 3),
        "median_tpot_ms": (
            round(
                statistics.median(
                    statistics.fmean(x["itl_ms"]) for x in samples if x["itl_ms"]
                ),
                3,
            )
            if any(x["itl_ms"] for x in samples)
            else None
        ),
    }


def main():
    record = json.loads(Path("live-run.json").read_text())
    print(
        json.dumps(
            {
                "execution_mode": "offline analysis of fresh local inference record",
                "model": record["model"],
                "generation": record["generation"],
                "comparisons": {
                    run["name"]: summarize(run["samples"]) for run in record["runs"]
                },
                "batch_sweep": record["batch_sweep"],
                "prefix_reuse": record["prefix_reuse"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
