"""Group a pytest-json-report run by perturbation and list flips: perturbed fails, original passes."""
import json
import re
import sys
from collections import Counter


def summarize(report: dict) -> dict:
    outcome = {t["nodeid"].split("::")[1]: t["outcome"] for t in report["tests"]}
    totals, passed, flips = Counter(), Counter(), []
    for test, result in outcome.items():
        name, params = re.fullmatch(r"(\w+)\[(.+)\]", test).groups()
        group = {"test_original": "original", "test_adversarial": "adversarial"}.get(name) or params.split("-", 1)[0]
        if name == "test_label_survives":
            case = params.split("-", 1)[1]
            if result != "passed" and outcome[f"test_original[{case}]"] == "passed":
                flips.append(params)
        totals[group] += 1
        passed[group] += result == "passed"
    return {"groups": {g: f"{passed[g]}/{totals[g]}" for g in totals}, "flips": flips}


if __name__ == "__main__":
    result = summarize(json.load(open(sys.argv[1])))
    for group, score in result["groups"].items():
        print(f"{group:<13}{score:>6}")
    print("flips:", ", ".join(result["flips"]) or "none")
