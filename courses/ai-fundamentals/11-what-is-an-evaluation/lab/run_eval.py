"""Run every eval case three times against the docs assistant and grade each answer. Run: python run_eval.py"""
import json
from pathlib import Path

import ollama
from pydantic import ValidationError

from assistant import NULL_RULE, DocsAnswer, DocsAnswerV2, ask

HERE = Path(__file__).parent
CASES = json.loads((HERE / "cases.json").read_text())


def grade(case: dict, answer: DocsAnswer) -> list[str]:
    """Reasons the answer fails this case; an empty list is a pass."""
    text = " ".join(filter(None, [answer.answer, answer.command])).replace("`", "").lower()
    problems = [f"cited {answer.source}, expected {case['source']}"] if answer.source != case["source"] else []
    problems += [f"missing {phrase!r}" for phrase in case["must_include"] if phrase.lower() not in text]
    return problems


def run_case(client: ollama.Client, case: dict, seed: int, answer_type=DocsAnswer, rules: str = "") -> dict:
    try:
        answer = ask(client, case["question"], answer_type=answer_type, rules=rules, temperature=0.7, seed=seed)
    except ValidationError as error:
        return {"case": case["id"], "seed": seed, "passed": False, "problems": [f"invalid output: {error.errors()[0]['type']}"]}
    problems = grade(case, answer)
    return {"case": case["id"], "seed": seed, "passed": not problems, "problems": problems,
            "answer": answer.model_dump()}


def report(label: str, results: list[dict]) -> dict:
    print(f"--- {label}")
    counts = {}
    for case in CASES:
        rows = [r for r in results if r["case"] == case["id"]]
        counts[case["id"]] = sum(r["passed"] for r in rows)
        problems = sorted({p for r in rows for p in r["problems"]})
        print(f"{case['id']:<17} {counts[case['id']]}/3  {'; '.join(problems)}")
    print(f"passed {sum(counts.values())} of {len(results)} trials\n")
    return counts


def main() -> None:
    client = ollama.Client()
    runs = {}
    versions = [("v1: source is required", DocsAnswer, ""),
                ("v2: source may be null", DocsAnswerV2, ""),
                ("v3: source may be null, prompt says when", DocsAnswerV2, NULL_RULE)]
    for label, answer_type, rules in versions:
        results = [run_case(client, case, seed, answer_type, rules) for case in CASES for seed in (1, 2, 3)]
        runs[label] = {"results": results, "passed": report(label, results)}
    output = HERE / "runs/local-docuctl"
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(runs, indent=1) + "\n")
    baseline, *_, latest = (run["passed"] for run in runs.values())
    print("v3 regressions against v1:", [case for case in baseline if latest[case] < baseline[case]] or "none")


if __name__ == "__main__":
    main()
