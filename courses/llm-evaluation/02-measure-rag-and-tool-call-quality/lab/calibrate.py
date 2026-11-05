"""Calibrate the judge: answers and contexts with a known defect must score below the threshold."""
import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
from deepeval.metrics import ContextualRecallMetric, FaithfulnessMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

from cassette import Cassette  # noqa: E402
from evaluate import JUDGE_MODEL, THRESHOLD, make_judge, sha  # noqa: E402

HERE = Path(__file__).parent
REPEATS = 3
METRICS = {
    "faithfulness": lambda judge: FaithfulnessMetric(THRESHOLD, model=judge, async_mode=False),
    # Borderline verdicts count as unsupported instead of supported.
    "faithfulness_strict": lambda judge: FaithfulnessMetric(THRESHOLD, model=judge, async_mode=False,
                                                            penalize_ambiguous_claims=True),
    "contextual_recall": lambda judge: ContextualRecallMetric(THRESHOLD, model=judge, async_mode=False),
}


def score(metric: str, case: dict, judge) -> dict:
    m = METRICS[metric](judge)
    m.measure(LLMTestCase(input=case["question"], actual_output=case["answer"],
                          expected_output=case["reference"], retrieval_context=case["context"]))
    return {"score": m.score, "reason": m.reason}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="call the judge and rewrite the recording")
    cases = json.loads((HERE / "calibration-cases.json").read_text())
    key = {"cases": f"{cases['name']}@{cases['version']}", "cases_sha": sha(cases), "judge": JUDGE_MODEL, "repeats": REPEATS}
    tape = Cassette(HERE / "recordings" / "calibration.json", key, parser.parse_args().live)
    judge = make_judge() if tape.live else None
    rows = []
    for case in cases["cases"]:
        scores = [tape.get(f"{case['id']}/{i}", lambda: score(case["metric"], case, judge))["score"] for i in range(REPEATS)]
        rows.append({"id": case["id"], "metric": case["metric"], "defect": case["defect"], "scores": scores,
                     "caught": all(s < THRESHOLD for s in scores)})
    if tape.live:
        tape.save()
    (HERE / "runs" / "calibration.json").write_text(json.dumps({"threshold": THRESHOLD, "rows": rows}, indent=2) + "\n")
    for r in rows:
        print(f"{r['id']:<26}{r['metric']:<21}{[round(x, 2) for x in r['scores']]}  {'caught' if r['caught'] else 'MISSED'}")


if __name__ == "__main__":
    main()
