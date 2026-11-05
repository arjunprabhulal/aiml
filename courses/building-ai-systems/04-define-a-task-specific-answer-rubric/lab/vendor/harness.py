"""A versioned evaluation harness with deterministic checks.

Load a case set and a task module, run a system on chosen splits, grade every
trial, and write one run record with the versions and hashes that produced it.
Compare two run records only when they were measured the same way. The core
knows no task: output fields, expected outcomes and graders come from the task
module. Python standard library only.
"""
import argparse
import copy
import hashlib
import importlib
import json
import platform
import re
import time
from datetime import datetime, timezone
from pathlib import Path

HARNESS_VERSION = "1"
HARNESS_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SPLITS = ("development", "held_out")
VERDICTS = ("pass", "fail", "incomplete")
CASE_KEYS = {"id", "split", "class", "input", "expected", "fail_if", "why"}
# Fields that describe one run rather than its results. They change on every rerun;
# everything else in a run record or recording reproduces exactly.
RUN_DESCRIPTION_FIELDS = ("latency_s", "recorded_latency_s", "started_at", "environment")
SCALARS = (str, int, float, bool, type(None))


class CaseError(ValueError):
    """The case file breaks the case contract."""


class RunError(ValueError):
    """A run or comparison was requested with inputs that cannot be trusted."""


class RecordedError(RuntimeError):
    """A replayed trial whose live run raised an error, with its original type names."""

    def __init__(self, types, message):
        super().__init__(message)
        self.types = types


class Answer:
    """What respond() may return instead of a bare output: the output plus metadata,
    such as token usage or a sampling seed, stored with the trial's result row."""

    def __init__(self, output, metadata=None):
        self.output, self.metadata = output, dict(metadata or {})


def canonical(value):
    """Serialize JSON with fixed key order so equal data hashes equally."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def without_run_description(value):
    """A copy of a run record or recording without RUN_DESCRIPTION_FIELDS, for comparing reruns."""
    if isinstance(value, dict):
        return {k: without_run_description(v) for k, v in value.items() if k not in RUN_DESCRIPTION_FIELDS}
    if isinstance(value, list):
        return [without_run_description(v) for v in value]
    return value


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunError(f"cannot read {path}: {error}") from None


def load_task(spec):
    """Import a task module: OUTPUT_FIELDS, validate_expected, GRADERS, NAME and VERSION."""
    try:
        module = importlib.import_module(spec)
    except ImportError as error:
        raise RunError(f"cannot load task {spec!r}: {error}") from None
    for attribute in ("NAME", "VERSION", "OUTPUT_FIELDS", "validate_expected", "GRADERS"):
        if not hasattr(module, attribute):
            raise RunError(f"task {spec} is missing {attribute}")
    module.SHA256 = sha256_file(module.__file__)
    return module


def check_expected(case_id, expected, task):
    if not isinstance(expected, dict) or not expected:
        raise CaseError(f"{case_id}: expected must be a nonempty object")
    if "rejected" in expected:
        # A required rejection: an error type name, optionally with a message pattern.
        if set(expected) - {"rejected", "message"} or not isinstance(expected["rejected"], str) \
                or not expected["rejected"] or not isinstance(expected.get("message", ""), str):
            raise CaseError(f"{case_id}: a rejection needs a nonempty error type and an optional message pattern")
        try:
            re.compile(expected.get("message", ""))
        except re.error as error:
            raise CaseError(f"{case_id}: rejection message pattern is not a valid regular expression: {error}") from None
        return
    try:
        task.validate_expected(expected)
    except ValueError as error:
        raise CaseError(f"{case_id}: {error}") from None


def check_conditions(case_id, conditions, task):
    """Every fail_if condition must name output fields with values of the field's type."""
    if not isinstance(conditions, list):
        raise CaseError(f"{case_id}: fail_if must be a list")
    for condition in conditions:
        if not isinstance(condition, dict) or not condition:
            raise CaseError(f"{case_id}: each fail_if condition must be a nonempty object")
        for field, value in condition.items():
            kind = task.OUTPUT_FIELDS.get(field)
            if kind is None or not isinstance(value, SCALARS) or type(value) is not kind:
                raise CaseError(f"{case_id}: fail_if field {field!r} must be one of "
                                f"{sorted(task.OUTPUT_FIELDS)} with a matching value type")


def load_cases(path, task):
    """Read and validate a case set. Its SHA-256 identifies this exact version."""
    data = read_json(path)
    if not isinstance(data, dict) or set(data) != {"name", "task", "cases"}:
        raise CaseError("case file must be an object with exactly name, task and cases")
    if not isinstance(data["name"], str) or not data["name"] or not isinstance(data["task"], str):
        raise CaseError("case set needs a name and a task description")
    if not isinstance(data["cases"], list) or not data["cases"]:
        raise CaseError("case set has no cases")
    seen = set()
    for case in data["cases"]:
        if not isinstance(case, dict):
            raise CaseError("every case must be a JSON object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise CaseError(f"case id must be unique, nonempty text: {case_id!r}")
        seen.add(case_id)
        if set(case) - CASE_KEYS or not {"id", "split", "class", "input", "expected", "fail_if"} <= set(case):
            raise CaseError(f"{case_id}: keys must be {sorted(CASE_KEYS)} (why is optional)")
        if case["split"] not in SPLITS:
            raise CaseError(f"{case_id}: split must be one of {SPLITS}")
        if not isinstance(case["class"], str) or not case["class"] or not isinstance(case.get("why", ""), str):
            raise CaseError(f"{case_id}: class must be nonempty text and why must be text")
        check_expected(case_id, case["expected"], task)
        check_conditions(case_id, case["fail_if"], task)
    # Hash the parsed JSON with sorted keys: whitespace and key order in the file do
    # not change the version; any changed value, or a change in case order, does.
    return dict(data, sha256=hashlib.sha256(canonical(data).encode("utf-8")).hexdigest())


def failure_criteria_check(case, output):
    for condition in case["fail_if"]:
        if all(output.get(field) == value for field, value in condition.items()):
            return False, f"failure criterion met: {canonical(condition)}"
    return True, ""


# The core adds this grader after the task's graders; it needs only OUTPUT_FIELDS.
CORE_GRADERS = ({"name": "failure-criteria", "version": HARNESS_VERSION, "kind": "outcome",
                 "check": failure_criteria_check},)


def error_types(error):
    """The error's class and base class names, so a ValueError subclass still matches."""
    if isinstance(error, RecordedError):
        return error.types
    return [cls.__name__ for cls in type(error).__mro__ if cls not in (BaseException, object)]


def judge_error(case, error):
    """An error is a pass only when the case requires that rejection with that message."""
    expected, reason = case["expected"], f"{error_types(error)[0]}: {error}"
    if expected.get("rejected") not in error_types(error):
        return {"verdict": "incomplete", "check": None, "kind": None, "reason": reason}
    if not re.search(expected.get("message", ""), str(error)):
        return {"verdict": "fail", "check": "rejection", "kind": "outcome",
                "reason": f"rejected for another reason: {reason}"}
    return {"verdict": "pass", "check": None, "kind": None, "reason": f"rejected as expected: {reason}"}


def grade(case, output, graders):
    if "rejected" in case["expected"]:
        return {"verdict": "fail", "check": "rejection", "kind": "outcome",
                "reason": f"expected a {case['expected']['rejected']} rejection, got an output"}
    for grader in graders:
        ok, reason = grader["check"](case, output)
        if not ok:
            return {"verdict": "fail", "check": grader["name"], "kind": grader["kind"], "reason": reason}
    return {"verdict": "pass", "check": None, "kind": None, "reason": ""}


def call(system, case, trial):
    """Call the system once; return (output, metadata, latency_s) or raise its error."""
    start = time.perf_counter()
    try:
        result = system.respond(case, trial)
    finally:
        latency = round(time.perf_counter() - start, 6)
    if isinstance(result, Answer) or (hasattr(result, "output") and hasattr(result, "metadata")):
        return result.output, dict(result.metadata), latency
    return result, {}, latency


def system_identity(system):
    return {"name": system.name, "version": system.version, "mode": system.mode,
            **{key: getattr(system, key, None) for key in ("model", "prompt", "tools")}}


class LiveSystem:
    """Wraps a function with a name, a version and optional model, prompt and tool versions."""

    mode = "live"

    def __init__(self, name, version, function, model=None, prompt=None, tools=None):
        self.name, self.version, self.function = name, version, function
        self.model, self.prompt, self.tools = model, prompt, tools

    def respond(self, case, trial):
        return self.function(case["input"])


class ReplaySystem:
    """Answers from a recording, so a run needs no model, network or randomness."""

    mode = "replay"

    def __init__(self, path, case_set):
        recording = read_json(path)
        try:
            identity, self.splits = recording["system"], recording["splits"]
            self.trials, self.responses = recording["trials"], recording["responses"]
            self.name, self.version = identity["name"], identity["version"]
            self.model, self.prompt, self.tools = identity["model"], identity["prompt"], identity["tools"]
            made_for = recording["case_set_sha256"]
        except (KeyError, TypeError):
            raise RunError(f"{path} is not a recording made by record()") from None
        if made_for != case_set["sha256"]:
            raise RunError("recording was made for a different case set version")
        # Hash the recorded results, not the timings: re-recording the same outputs
        # gives the same hash even though every latency_s value changes.
        self.sha256 = hashlib.sha256(canonical(without_run_description(recording)).encode("utf-8")).hexdigest()

    def check_plan(self, splits, trials):
        """A replay must use exactly the splits and trial count that were recorded."""
        if sorted(set(splits)) != self.splits or trials != self.trials:
            raise RunError(f"recording holds splits {self.splits} with {self.trials} trial(s) per case; "
                           f"asked for {sorted(set(splits))} with {trials}")

    def respond(self, case, trial):
        try:
            recorded = self.responses[case["id"]][trial]
        except (KeyError, IndexError):
            raise LookupError("no recorded response for this case and trial") from None
        if "error" in recorded:
            raise RecordedError(recorded["error"]["types"], recorded["error"]["message"])
        # A copy, so nothing downstream can change the recording between runs.
        metadata = dict(copy.deepcopy(recorded["metadata"]), recorded_latency_s=recorded["latency_s"])
        return Answer(copy.deepcopy(recorded["output"]), metadata)


def plan(case_set, splits, trials, include_held_out):
    if not splits or set(splits) - set(SPLITS):
        raise RunError(f"splits must be chosen from {SPLITS}")
    if "held_out" in splits and not include_held_out:
        raise RunError("held-out cases run only when explicitly included (--include-held-out)")
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        raise RunError("trials must be a positive integer")
    return [case for case in case_set["cases"] if case["split"] in splits]


def record(system, case_set, splits, trials=1, include_held_out=False):
    """Run a live system and save its outputs or errors, latency and metadata for replay."""
    responses = {}
    for case in plan(case_set, splits, trials, include_held_out):
        responses[case["id"]] = []
        for trial in range(trials):
            start = time.perf_counter()
            try:
                output, metadata, latency = call(system, case, trial)
                responses[case["id"]].append({"output": output, "metadata": metadata, "latency_s": latency})
            except Exception as error:
                responses[case["id"]].append({"error": {"types": error_types(error), "message": str(error)},
                                              "latency_s": round(time.perf_counter() - start, 6)})
    return {"harness_version": HARNESS_VERSION, "system": system_identity(system),
            "case_set_sha256": case_set["sha256"], "splits": sorted(set(splits)), "trials": trials,
            "responses": responses}


def run(system, case_set, task, splits=("development",), trials=1, include_held_out=False):
    """Grade every trial of every selected case and return one run record."""
    cases = plan(case_set, splits, trials, include_held_out)
    if hasattr(system, "check_plan"):
        system.check_plan(splits, trials)
    graders = tuple(task.GRADERS) + CORE_GRADERS
    results = []
    for case in cases:
        for trial in range(trials):
            row = {"case_id": case["id"], "split": case["split"], "class": case["class"], "trial": trial}
            start = time.perf_counter()
            try:
                output, metadata, latency = call(system, case, trial)
            except Exception as error:  # No output exists; only a required rejection can pass.
                row.update(judge_error(case, error), output=None, metadata={},
                           latency_s=round(time.perf_counter() - start, 6))
            else:
                if output is None:  # Returned nothing: still no output to grade.
                    verdict = {"verdict": "incomplete", "check": None, "kind": None, "reason": "no output (returned None)"}
                else:
                    verdict = grade(case, output, graders)
                row.update(verdict, output=output, metadata=metadata, latency_s=latency)
            results.append(row)
    return {
        "manifest": {
            "harness_version": HARNESS_VERSION,
            "harness_sha256": HARNESS_SHA256,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "case_set": {"name": case_set["name"], "sha256": case_set["sha256"]},
            "task": {"name": task.NAME, "version": task.VERSION, "sha256": task.SHA256},
            "system": system_identity(system),
            "recording_sha256": getattr(system, "sha256", None),
            "graders": [{key: grader[key] for key in ("name", "version", "kind")} for grader in graders],
            "splits": sorted(set(splits)),
            "trials": trials,
            "environment": {"python": platform.python_version(), "platform": platform.platform()},
        },
        "summary": summarize(results, trials),
        "results": results,
    }


def summarize(results, trials):
    summary = {}
    for split in sorted({row["split"] for row in results}):
        rows = [row for row in results if row["split"] == split]
        per_case = {}
        for row in rows:
            counts = per_case.setdefault(row["case_id"], dict.fromkeys(VERDICTS, 0))
            counts[row["verdict"]] += 1
        summary[split] = {
            "cases": len(per_case), "trials": len(rows),
            **{verdict: sum(row["verdict"] == verdict for row in rows) for verdict in VERDICTS},
            "cases_passing_any_trial": sum(c["pass"] > 0 for c in per_case.values()),
            "cases_passing_every_trial": sum(c["pass"] == trials for c in per_case.values()),
            "per_case": per_case,
        }
    return summary


CHANGES = ("fixed", "regressed", "changed", "unchanged")
# Fields that must match for two runs to be comparable. The task and harness hashes
# catch a grader edit even when nobody raised a version number.
COMPARABLE = ("harness_version", "harness_sha256", "case_set", "task", "graders", "splits", "trials")


def compare(baseline, candidate):
    """Report per-case changes. Refuse runs that were not measured the same way."""
    for field in COMPARABLE:
        if baseline["manifest"][field] != candidate["manifest"][field]:
            raise RunError(f"runs differ in {field}; their verdicts are not comparable")

    def verdicts(record):
        table = {}
        for row in record["results"]:
            table.setdefault((row["split"], row["case_id"]), []).append(row["verdict"])
        return table

    before, after = verdicts(baseline), verdicts(candidate)
    if set(before) != set(after):
        raise RunError("runs cover different cases; their verdicts are not comparable")
    rows = []
    for split, case_id in sorted(before, key=lambda key: (SPLITS.index(key[0]), key[1])):
        old, new = before[(split, case_id)], after[(split, case_id)]
        old_pass, new_pass = all(v == "pass" for v in old), all(v == "pass" for v in new)
        # fixed and regressed compare "passed every trial"; changed means the
        # per-trial verdicts moved while neither run passed every trial.
        change = "fixed" if new_pass and not old_pass else "regressed" if old_pass and not new_pass \
            else "unchanged" if old == new else "changed"
        rows.append({"split": split, "case_id": case_id, "baseline": old, "candidate": new, "change": change})
    summary = {}
    for split in baseline["summary"]:
        sides = {side: {k: v for k, v in record["summary"][split].items() if k != "per_case"}
                 for side, record in (("baseline", baseline), ("candidate", candidate))}
        summary[split] = {**sides, **{change: sum(r["change"] == change for r in rows if r["split"] == split)
                                      for change in CHANGES}}
    return {"baseline": baseline["manifest"]["system"], "candidate": candidate["manifest"]["system"],
            "case_set": baseline["manifest"]["case_set"], "task": baseline["manifest"]["task"],
            "summary": summary, "cases": rows}


def load_system(spec, case_set):
    """`replay:<recording.json>` or `<module>:<attribute>` naming a LiveSystem."""
    kind, colon, target = spec.partition(":")
    if not colon or not kind or not target:
        raise RunError(f"system must be replay:<file> or <module>:<attribute>, not {spec!r}")
    if kind == "replay":
        return ReplaySystem(target, case_set)
    try:
        system = getattr(importlib.import_module(kind), target)
    except (ImportError, AttributeError) as error:
        raise RunError(f"cannot load system {spec!r}: {error}") from None
    for attribute in ("name", "version", "mode", "respond"):
        if not hasattr(system, attribute):
            raise RunError(f"{spec} is not a system: missing {attribute}")
    return system


def write(path, value):
    try:
        Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as error:
        raise RunError(f"cannot write {path}: {error}") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "record"):
        command = commands.add_parser(name)
        command.add_argument("--task", required=True, help="task module, such as triage_task")
        command.add_argument("--cases", required=True)
        command.add_argument("--system", required=True)
        command.add_argument("--split", action="append", choices=SPLITS, required=True)
        command.add_argument("--include-held-out", action="store_true")
        command.add_argument("--trials", type=int, default=1)
        command.add_argument("--out", required=True)
    compare_command = commands.add_parser("compare")
    compare_command.add_argument("baseline")
    compare_command.add_argument("candidate")
    compare_command.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    if args.command == "compare":
        report = compare(read_json(args.baseline), read_json(args.candidate))
        write(args.out, report)
        for split, data in report["summary"].items():
            print(f"{split}: baseline {data['baseline']['pass']} pass, candidate {data['candidate']['pass']} pass, "
                  f"fixed {data['fixed']}, regressed {data['regressed']}, changed {data['changed']}")
        return
    task = load_task(args.task)
    case_set = load_cases(args.cases, task)
    system = load_system(args.system, case_set)
    if args.command == "record":
        write(args.out, record(system, case_set, args.split, args.trials, args.include_held_out))
        print(f"recorded {system.name} v{system.version} for {sorted(set(args.split))}, {args.trials} trial(s)")
        return
    report = run(system, case_set, task, args.split, args.trials, args.include_held_out)
    write(args.out, report)
    for split, data in report["summary"].items():
        print(f"{split}: {data['pass']} pass, {data['fail']} fail, {data['incomplete']} incomplete "
              f"of {data['trials']} trials")


if __name__ == "__main__":
    try:
        main()
    except (CaseError, RunError) as error:
        raise SystemExit(f"error: {error}")  # Exit status 1, message on stderr.
