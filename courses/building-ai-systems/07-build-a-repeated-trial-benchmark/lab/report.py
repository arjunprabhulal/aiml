"""Read repeated-trial run records and report what a single trial would hide.

For each system: verdict counts, failures by check and incomplete trials by
error type, every case's pass count, the flaky cases (some trials pass, some
do not), estimates of pass@k and pass^k for every k up to the trial count, and
the median and 90th-percentile latency of the trials that returned an output.
Trials the benchmark never ran (NotRun) are counted on their own. They are not
flakiness, and a run with any of them gets no pass@k or pass^k: resume it first.
Python standard library only.
Run: python3 report.py runs/gemma.json runs/qwen.json --out runs/report.json
"""
import argparse
import math
from collections import Counter

from harness import RunError, read_json, write

REPORT_VERSION = "1"


def pass_at_k(n, c, k):
    """Chance that at least one of k trials drawn without replacement from n passes (c passed)."""
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_power_k(n, c, k):
    """Chance that all k trials drawn without replacement from n pass (c passed)."""
    return math.comb(c, k) / math.comb(n, k)


def nearest_rank(values, share):
    """The smallest value with at least `share` of the values at or below it."""
    ordered = sorted(values)
    return ordered[max(1, math.ceil(share * len(ordered))) - 1]


def first_word(reason):
    return reason.split(":", 1)[0]


def system_report(record):
    manifest, results = record["manifest"], record["results"]
    if manifest["splits"] != ["development"]:
        raise RunError("the benchmark reports development runs only")
    n = manifest["trials"]
    per_case = {}
    for row in results:
        counts = per_case.setdefault(row["case_id"], {"class": row["class"], "pass": 0, "fail": 0, "incomplete": 0,
                                                       "not_run": 0})
        counts[row["verdict"]] += 1
        counts["not_run"] += row["verdict"] == "incomplete" and first_word(row["reason"]) == "NotRun"
    if any(sum(c[v] for v in ("pass", "fail", "incomplete")) != n for c in per_case.values()):
        raise RunError("every case must have exactly one row per trial")
    latencies = [row["metadata"]["recorded_latency_s"] for row in results
                 if row["output"] is not None and "recorded_latency_s" in row["metadata"]]
    not_run = sum(c["not_run"] for c in per_case.values())
    curve = None if not_run else {str(k): {"pass_at_k": round(math.fsum(pass_at_k(n, c["pass"], k) for c in per_case.values()) / len(per_case), 4),
                      "pass_power_k": round(math.fsum(pass_power_k(n, c["pass"], k) for c in per_case.values()) / len(per_case), 4)}
             for k in range(1, n + 1)}
    return {
        "system": manifest["system"],
        "recording_sha256": manifest["recording_sha256"],
        "trials_per_case": n,
        "cases": len(per_case),
        "verdicts": dict(Counter(row["verdict"] for row in results)),
        "not_run": not_run,
        "failures_by_check": dict(sorted(Counter(row["check"] for row in results if row["verdict"] == "fail").items())),
        "incomplete_by_error": dict(sorted(Counter(first_word(row["reason"]) for row in results
                                                   if row["verdict"] == "incomplete").items())),
        "per_case": per_case,
        # Flaky: among the trials that ran, some passed and some did not.
        "flaky_cases": [case for case, c in per_case.items() if 0 < c["pass"] < n - c["not_run"]],
        "never_passed": [case for case, c in per_case.items() if c["pass"] == 0],
        "curve": curve,
        "latency_s": ({"trials": len(latencies), "median": round(nearest_rank(latencies, 0.5), 3),
                       "p90": round(nearest_rank(latencies, 0.9), 3)} if latencies else None),
    }


def build_report(records):
    task = {r["manifest"]["task"]["sha256"] for r in records}
    cases = {r["manifest"]["case_set"]["sha256"] for r in records}
    if len(task) != 1 or len(cases) != 1:
        raise RunError("all run records must use the same task module and case set")
    return {"report_version": REPORT_VERSION, "case_set": records[0]["manifest"]["case_set"],
            "systems": [system_report(record) for record in records]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report = build_report([read_json(path) for path in args.runs])
    write(args.out, report)
    for system in report["systems"]:
        last = str(system["trials_per_case"])
        estimate = (f"pass@{last} {system['curve'][last]['pass_at_k']}, pass^{last} {system['curve'][last]['pass_power_k']}"
                    if system["curve"] else f"no pass@k: {system['not_run']} trials not run")
        print(f"{system['system']['name']}: {system['verdicts']}; flaky {len(system['flaky_cases'])} of "
              f"{system['cases']} cases; {estimate}")


if __name__ == "__main__":
    try:
        main()
    except RunError as error:
        raise SystemExit(f"error: {error}")
