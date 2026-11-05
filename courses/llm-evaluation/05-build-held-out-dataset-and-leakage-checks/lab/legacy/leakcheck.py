"""Check a case set's held-out split for overlap, leakage and unrecorded changes.

Five checks, each with a severity. A "block" finding means the held-out cases
can no longer measure the system honestly; a "review" finding needs a person.
- overlap (block): a development and a held-out input are the same text, or
  share most of their words, after normalizing case, punctuation and spaces.
- source (block): a generated case and its source case are in different splits.
- copied (block): four consecutive words of a held-out input appear in a
  system artifact, such as a prompt or a rule file.
- held-out-only term (review): a string in an artifact appears in at least one
  held-out input and in no development input. It may come from general
  knowledge, or from someone reading the held-out cases.
- lock (block): a held-out case was edited, added or removed since the lock
  file was written, or moved to development.
It also counts the run records that ran the held-out split of this case set.
Python standard library only.
Run: python3 leakcheck.py check --cases cases.json --artifact artifacts/triage.py --records records/*.json --out runs/check.json
"""
import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

import harness

CHECK_VERSION = "1"
NEAR_DUPLICATE = 0.6  # Word-set Jaccard similarity at or above this is an overlap.
SHINGLE = 4           # Consecutive words that count as copied text.
MIN_TERM = 3          # Shorter artifact strings are ignored as terms.


class LeakError(ValueError):
    """An input file breaks its contract."""


def normalize(text):
    """Lowercase, keep letters and digits (any script), collapse everything else to single spaces."""
    return " ".join(re.findall(r"[^\W_]+", text.lower()))


def words(text):
    return normalize(text).split()


def jaccard(a, b):
    a, b = set(words(a)), set(words(b))
    return len(a & b) / len(a | b) if a | b else 0.0


def shingles(text, size=SHINGLE):
    w = words(text)
    return {" ".join(w[i:i + size]) for i in range(len(w) - size + 1)}


def case_hash(case):
    return hashlib.sha256(harness.canonical(case).encode("utf-8")).hexdigest()


def text_cases(case_set, split):
    return [c for c in case_set["cases"] if c["split"] == split and isinstance(c["input"], str) and c["input"].strip()]


def artifact_strings(path):
    """String constants in a Python file, without docstrings; every line of any other file."""
    source = Path(path).read_text(encoding="utf-8")
    if not str(path).endswith(".py"):
        return [line for line in source.splitlines() if line.strip()]
    tree = ast.parse(source)
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)}
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]


def check_overlap(case_set):
    findings = []
    for dev in text_cases(case_set, "development"):
        for held in text_cases(case_set, "held_out"):
            similarity = jaccard(dev["input"], held["input"])
            if normalize(dev["input"]) == normalize(held["input"]) or similarity >= NEAR_DUPLICATE:
                findings.append({"check": "overlap", "severity": "block", "development": dev["id"],
                                 "held_out": held["id"], "similarity": round(similarity, 4)})
    return findings


def check_sources(case_set):
    split_of = {c["id"]: c["split"] for c in case_set["cases"]}
    findings = []
    for case in case_set["cases"]:
        source = case.get("tags", {}).get("source")
        if source and source != case["id"]:
            if source not in split_of:
                findings.append({"check": "source", "severity": "block", "case": case["id"],
                                 "reason": f"source {source!r} is not in the case set"})
            elif split_of[source] != case["split"]:
                findings.append({"check": "source", "severity": "block", "case": case["id"],
                                 "reason": f"in {case['split']}, its source {source!r} is in {split_of[source]}"})
    return findings


def check_artifact(path, case_set):
    strings = artifact_strings(path)
    artifact_text = " " + " ".join(normalize(s) for s in strings) + " "
    findings = []
    for held in text_cases(case_set, "held_out"):
        copied = sorted(s for s in shingles(held["input"]) if f" {s} " in artifact_text)
        if copied:
            findings.append({"check": "copied", "severity": "block", "artifact": Path(path).name,
                             "held_out": held["id"], "words": copied[0]})
    dev_texts = [" " + normalize(c["input"]) + " " for c in text_cases(case_set, "development")]
    held = text_cases(case_set, "held_out")
    for term in sorted({normalize(s) for s in strings if len(normalize(s)) >= MIN_TERM}):
        in_held = [c["id"] for c in held if term in normalize(c["input"])]
        if in_held and not any(term in text for text in dev_texts):
            findings.append({"check": "held-out-only term", "severity": "review", "artifact": Path(path).name,
                             "term": term, "held_out": in_held})
    return findings


def lock(case_set):
    """The held-out cases' hashes at the moment the split is frozen."""
    return {"check_version": CHECK_VERSION, "case_set": case_set["name"],
            "held_out": {c["id"]: case_hash(c) for c in case_set["cases"] if c["split"] == "held_out"}}


def check_lock(locked, case_set):
    if not isinstance(locked, dict) or not isinstance(locked.get("held_out"), dict):
        raise LeakError("the lock file must hold a held_out object of case IDs and hashes")
    current = {c["id"]: c for c in case_set["cases"]}
    findings = []
    for case_id, digest in locked["held_out"].items():
        case = current.get(case_id)
        if case is None:
            findings.append({"check": "lock", "severity": "block", "case": case_id, "reason": "removed"})
        elif case["split"] != "held_out":
            findings.append({"check": "lock", "severity": "block", "case": case_id, "reason": f"moved to {case['split']}"})
        elif case_hash(case) != digest:
            findings.append({"check": "lock", "severity": "block", "case": case_id, "reason": "edited"})
    for case in case_set["cases"]:
        if case["split"] == "held_out" and case["id"] not in locked["held_out"]:
            findings.append({"check": "lock", "severity": "block", "case": case["id"], "reason": "added after the lock"})
    return findings


def held_out_runs(paths, case_set):
    """Run records of this exact case set that included the held-out split."""
    runs = []
    for path in paths:
        manifest = harness.read_json(path)["manifest"]
        if manifest["case_set"]["sha256"] == case_set["sha256"] and "held_out" in manifest["splits"]:
            runs.append({"record": Path(path).name, "system": f"{manifest['system']['name']} v{manifest['system']['version']}",
                         "started_at": manifest["started_at"]})
    return runs


def check(case_set, artifacts=(), locked=None, records=()):
    findings = check_overlap(case_set) + check_sources(case_set)
    for path in artifacts:
        findings += check_artifact(path, case_set)
    if locked is not None:
        findings += check_lock(locked, case_set)
    severities = {f["severity"] for f in findings}
    return {"check_version": CHECK_VERSION, "case_set": {"name": case_set["name"], "sha256": case_set["sha256"]},
            "cases": {split: sum(c["split"] == split for c in case_set["cases"]) for split in harness.SPLITS},
            "artifacts": [Path(p).name for p in artifacts], "locked": locked is not None,
            "decision": "block" if "block" in severities else "review" if "review" in severities else "pass",
            "findings": findings, "held_out_runs": held_out_runs(records, case_set)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "lock"):
        command = commands.add_parser(name)
        command.add_argument("--task", default="triage_task")
        command.add_argument("--cases", required=True)
        command.add_argument("--out", required=True)
        if name == "check":
            command.add_argument("--artifact", action="append", default=[])
            command.add_argument("--lock", help="lock file written by the lock command")
            command.add_argument("--records", nargs="*", default=[])
    args = parser.parse_args(argv)
    case_set = harness.load_cases(args.cases, harness.load_task(args.task))
    if args.command == "lock":
        harness.write(args.out, lock(case_set))
        print(f"locked {len(lock(case_set)['held_out'])} held-out cases of {case_set['name']}")
        return 0
    locked = harness.read_json(args.lock) if args.lock else None
    result = check(case_set, args.artifact, locked, args.records)
    harness.write(args.out, result)
    print(f"{result['decision']}: {len(result['findings'])} finding(s); "
          f"{len(result['held_out_runs'])} run record(s) included the held-out split")
    for finding in result["findings"]:
        print("  " + json.dumps(finding, ensure_ascii=False))
    return 1 if result["decision"] == "block" else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (harness.CaseError, harness.RunError, LeakError, SyntaxError) as error:
        raise SystemExit(f"error: {error}")
