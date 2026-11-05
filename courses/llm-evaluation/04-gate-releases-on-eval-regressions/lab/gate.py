"""Regression gate: compare a candidate eval run with the baseline run and fail the job on a regression."""
import argparse
import json
import sys
from pathlib import Path

EXIT = {"pass": 0, "block": 1, "incomparable": 2}
COMPONENTS = ("model", "prompt_version", "prompt_sha")


def outcomes(report: dict) -> dict[str, str]:
    return {t["nodeid"]: t["outcome"] for t in report["tests"]}


def gate(baseline: dict, candidate: dict, policy: dict) -> dict:
    b, c = baseline["eval"], candidate["eval"]
    if b["dataset_sha"] != c["dataset_sha"]:
        return {"decision": "incomparable", "reasons": [
            f"baseline ran {b['dataset']} ({b['dataset_sha']}), candidate ran {c['dataset']} ({c['dataset_sha']}); "
            "rerun the baseline on the candidate's dataset"]}
    if b["judge_model"] != c["judge_model"]:
        return {"decision": "incomparable", "reasons": [
            f"judge changed from {b['judge_model']} to {c['judge_model']}; judged scores are not comparable"]}
    before, after = outcomes(baseline), outcomes(candidate)
    regressed = sorted(n for n, o in before.items() if o == "passed" and after.get(n) != "passed")
    fixed = sorted(n for n, o in before.items() if o != "passed" and after.get(n) == "passed")
    is_critical = lambda n: n.split("::")[-1].startswith(tuple(policy["critical"]))  # noqa: E731
    critical = sorted(n for n, o in after.items() if o != "passed" and is_critical(n))
    missing_critical = sorted(n for n in before if is_critical(n) and n not in after)
    pass_rate = sum(o == "passed" for o in after.values()) / len(after)
    reasons = []
    if len(regressed) > policy["max_regressions"]:
        reasons.append(f"{len(regressed)} regression(s); policy allows {policy['max_regressions']}")
    if critical:
        reasons.append(f"{len(critical)} critical test(s) fail")
    if missing_critical:
        reasons.append(f"{len(missing_critical)} critical test(s) from the baseline are missing from the candidate")
    if pass_rate < policy["min_pass_rate"]:
        reasons.append(f"pass rate {pass_rate:.3f} is below {policy['min_pass_rate']}")
    return {"decision": "block" if reasons else "pass", "reasons": reasons,
            "changed": {k: [b[k], c[k]] for k in COMPONENTS if b[k] != c[k]},
            "pass_rate": round(pass_rate, 3), "regressed": regressed, "fixed": fixed, "critical_failures": critical,
            "missing_critical": missing_critical}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--policy", type=Path, default=Path(__file__).with_name("policy.json"))
    parser.add_argument("--out", type=Path, help="write the decision as JSON")
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text())  # noqa: E731
    result = gate(load(args.baseline), load(args.candidate), load(args.policy))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"decision: {result['decision'].upper()}")
    for key in ("reasons", "changed", "regressed", "fixed", "critical_failures", "missing_critical"):
        if result.get(key):
            print(f"{key}: {json.dumps(result[key], indent=2)}")
    return EXIT[result["decision"]]


if __name__ == "__main__":
    sys.exit(main())
