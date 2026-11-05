"""Repeated-trial benchmark: run every case k times, log each trial, resume, stop on budget.

The harness's record() keeps every trial in memory and writes nothing until the
last one finishes, so a crash or a stopped run loses everything. bench.py
appends one JSON line per trial to a log as soon as the trial ends. Running it
again with the same log skips the trials already logged. A time budget stops
the run between trials. to_recording() turns a log into a harness recording in
which every trial that never ran is an error of type NotRun, so the harness
grades it incomplete instead of dropping it.
Python standard library only.
Run: python3 bench.py --system model_triage:gemma --trials 10 --log recorded/gemma.jsonl
"""
import argparse
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import harness

BENCH_VERSION = "1"
HEADER_KEYS = ("bench_version", "harness_version", "case_set_sha256", "system", "splits", "trials")


class BenchError(ValueError):
    """The log cannot be resumed or converted safely."""


def header_for(system, case_set, splits, trials):
    return {"bench_version": BENCH_VERSION, "harness_version": harness.HARNESS_VERSION,
            "case_set_sha256": case_set["sha256"], "system": harness.system_identity(system),
            "splits": sorted(set(splits)), "trials": trials}


def schedule(case_set, splits, trials):
    """Trial-major order: trial 0 of every case, then trial 1 of every case, and so on.
    A run stopped early then has the same number of trials for every case, plus or minus one."""
    cases = harness.plan(case_set, splits, trials, include_held_out=False)
    return [(case, trial) for trial in range(trials) for case in cases]


def read_log(path):
    """Return (header, rows). A truncated last line, from a crash mid-write, is ignored."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise BenchError(f"{path} is empty")
    header, rows = json.loads(lines[0]), []
    for number, line in enumerate(lines[1:], start=2):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if number != len(lines):
                raise BenchError(f"{path}: line {number} is not JSON") from None
    return header, rows


def run_bench(system, case_set, splits, trials, log_path, budget_s=None, clock=time.monotonic, hardware=None):
    """Run every planned trial not yet in the log. Return counts of what this call did."""
    log_path = Path(log_path)
    header = header_for(system, case_set, splits, trials)
    done = set()
    if log_path.exists() and log_path.stat().st_size:
        logged, rows = read_log(log_path)
        differs = [key for key in HEADER_KEYS if logged.get(key) != header[key]]
        if differs:
            raise BenchError(f"{log_path} was written for another {', '.join(differs)}; use a new log")
        done = {(row["case_id"], row["trial"]) for row in rows}
        with log_path.open("r+b") as handle:
            data = handle.read()
            if not data.endswith(b"\n"):
                tail_start = data.rfind(b"\n") + 1
                try:
                    json.loads(data[tail_start:])
                except (ValueError, UnicodeError):
                    handle.truncate(tail_start)  # Discard only an incomplete final JSON value.
                else:
                    handle.write(b"\n")  # Preserve a complete row already accepted by read_log().
    else:
        # started_at, budget_s and environment describe this run; a resume does not compare them.
        environment = {"python": platform.python_version(), "platform": platform.platform(), "hardware": hardware}
        log_path.write_text(json.dumps(dict(header, started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                            budget_s=budget_s, environment=environment), ensure_ascii=False) + "\n",
                            encoding="utf-8")
    start, ran, stopped = clock(), 0, False
    with log_path.open("a", encoding="utf-8") as log:
        for case, trial in schedule(case_set, splits, trials):
            if (case["id"], trial) in done:
                continue
            if budget_s is not None and clock() - start >= budget_s:
                stopped = True
                break
            row = {"case_id": case["id"], "trial": trial}
            call_start = time.perf_counter()
            try:
                output, metadata, latency = harness.call(system, case, trial)
                row.update(output=output, metadata=metadata, latency_s=latency)
            except Exception as error:  # Recorded, not raised: an error is a result.
                row.update(error={"types": harness.error_types(error), "message": str(error)},
                           latency_s=round(time.perf_counter() - call_start, 6))
                if hasattr(system, "seed_for"):  # A failed trial keeps its seed, so it can be rerun alone.
                    row["metadata"] = {"seed": system.seed_for(trial)}
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
            log.flush()  # The trial survives a crash of the next one.
            ran += 1
    planned = len(schedule(case_set, splits, trials))
    return {"planned": planned, "already_logged": len(done), "ran": ran,
            "not_run": planned - len(done) - ran, "stopped_by_budget": stopped}


def to_recording(log_path, case_set):
    """Convert a log into a harness recording. Every planned trial missing from the log
    becomes an error of type NotRun, so the harness counts it as incomplete."""
    header, rows = read_log(log_path)
    if header.get("case_set_sha256") != case_set["sha256"]:
        raise BenchError(f"{log_path} was written for a different case set version")
    by_key = {}
    for row in rows:
        key = (row["case_id"], row["trial"])
        if key in by_key:
            raise BenchError(f"{log_path}: {key[0]} trial {key[1]} is logged twice")
        by_key[key] = {k: row[k] for k in ("output", "metadata", "error", "latency_s") if k in row}
    responses = {}
    for case in harness.plan(case_set, header["splits"], header["trials"], include_held_out=False):
        responses[case["id"]] = [
            by_key.get((case["id"], trial),
                       {"error": {"types": ["NotRun"], "message": "not run: the benchmark stopped first"},
                        "latency_s": 0.0})
            for trial in range(header["trials"])]
    return {"harness_version": header["harness_version"], "system": header["system"],
            "case_set_sha256": header["case_set_sha256"], "splits": header["splits"],
            "trials": header["trials"], "responses": responses}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", default="triage_task")
    parser.add_argument("--cases", default="cases.json")
    parser.add_argument("--system", help="<module>:<attribute>; omit with --convert")
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument("--log", required=True)
    parser.add_argument("--budget-s", type=float, help="stop starting new trials after this many seconds")
    parser.add_argument("--hardware", help="a description of the machine, stored in a new log's header")
    parser.add_argument("--convert", metavar="RECORDING", help="write the log as a harness recording and exit")
    args = parser.parse_args(argv)
    case_set = harness.load_cases(args.cases, harness.load_task(args.task))
    if args.convert:
        harness.write(args.convert, to_recording(args.log, case_set))
        print(f"wrote {args.convert}")
        return
    system = harness.load_system(args.system, case_set)
    if hasattr(system, "check_model"):  # Check the digest once, before any trial is logged.
        try:
            system.check_model()
        except RuntimeError as error:
            raise BenchError(str(error)) from None
    counts = run_bench(system, case_set, ["development"], args.trials, args.log, args.budget_s, hardware=args.hardware)
    print(f"{system.name}: planned {counts['planned']}, already logged {counts['already_logged']}, "
          f"ran {counts['ran']}, not run {counts['not_run']}"
          + (" (stopped by the time budget)" if counts["stopped_by_budget"] else ""))


if __name__ == "__main__":
    try:
        main()
    except (harness.CaseError, harness.RunError, BenchError) as error:
        raise SystemExit(f"error: {error}")
