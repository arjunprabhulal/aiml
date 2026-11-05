"""Rank actual host operator records without inferring GPU utilization."""

import json, math
from pathlib import Path


def rank_operators(rows):
    if not rows:
        raise ValueError("Operator records are required")
    if any(
        not math.isfinite(r["self_cpu_us"]) or r["self_cpu_us"] < 0 or r["calls"] < 1
        for r in rows
    ):
        raise ValueError("Invalid host operator record")
    return sorted(rows, key=lambda r: r["self_cpu_us"], reverse=True)


def main():
    record = json.loads(Path("profile-run.json").read_text())
    print(
        json.dumps(
            {
                "execution_mode": "offline analysis of actual CPU profiler events around Metal model execution",
                "profiled_wall_ms": record["profiled_wall_ms"],
                "top_host_operators": rank_operators(record["operators"]),
                "limits": "Host operator time is not GPU kernel time, GPU utilization or device bandwidth. Profiling changes execution.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
