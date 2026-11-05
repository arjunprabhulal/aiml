"""Validate recorded numerical parity and summarize actual Metal expression timings."""

import json, math, statistics
from pathlib import Path


def compare_case(case, tolerance=1e-5):
    if (
        tolerance < 0
        or not math.isfinite(case["max_abs_error"])
        or case["max_abs_error"] > tolerance
    ):
        raise ValueError("Numerical parity exceeds tolerance")
    result = {
        "rows": case["rows"],
        "width": case["width"],
        "max_abs_error": case["max_abs_error"],
    }
    for name in ["eager", "compiled"]:
        samples = case["timings"][name]["samples_ms"]
        if not samples or any(not math.isfinite(v) or v <= 0 for v in samples):
            raise ValueError("Invalid timing samples")
        result[name + "_median_ms"] = round(statistics.median(samples), 6)
    return result


def main():
    record = json.loads(Path("fusion-run.json").read_text())
    print(
        json.dumps(
            {
                "execution_mode": "offline analysis of fresh Metal eager and compiled expression runs",
                "cases": [compare_case(c) for c in record["cases"]],
                "limits": "Shape-specific tensor timings; no Triton/CUDA run, device-memory counter or whole-model speedup.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
