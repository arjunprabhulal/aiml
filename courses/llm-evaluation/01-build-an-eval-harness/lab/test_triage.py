"""The triage eval: deterministic checks on every case, then one LLM-as-judge check."""
import pytest
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

from conftest import DATASET
from triage import Triage

every_case = pytest.mark.parametrize("case", DATASET.cases, ids=lambda c: c.id)
critical = [c for c in DATASET.cases if c.expected.priority]


@every_case
def test_reply_matches_schema(raw_output):
    Triage.model_validate_json(raw_output)


@every_case
def test_label(case, output):
    assert output.label == case.expected.label


@pytest.mark.parametrize("case", critical, ids=lambda c: c.id)
def test_priority(case, output):
    assert output.priority == case.expected.priority


@every_case
def test_summary_is_short_and_specific(case, output):
    words = output.summary.split()
    assert len(words) <= 20, f"{len(words)} words"
    missing = [term for term in case.must_mention if term not in output.summary.lower()]
    assert not missing, f"summary lacks {missing}: {output.summary!r}"


FAITHFUL = "The summary states only facts that are in the issue and keeps its main problem."
THRESHOLD = 0.7


def faithfulness(judge, issue: str, summary: str) -> dict:
    metric = GEval(
        name="Faithful summary",
        criteria=FAITHFUL,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=THRESHOLD,
        async_mode=False,
    )
    metric.measure(LLMTestCase(input=issue, actual_output=summary))
    return {"score": metric.score, "reason": metric.reason}


@every_case
def test_summary_is_faithful(case, output, cassette, judge):
    verdict = cassette.get(f"judge/{case.id}", lambda: faithfulness(judge(), case.issue, output.summary))
    assert verdict["score"] >= THRESHOLD, verdict["reason"]


def test_judge_rejects_an_invented_summary(cassette, judge):
    """Calibration: a judge that passes everything measures nothing."""
    issue = DATASET.cases[0].issue
    invented = "tracker sync is slow on Windows when the network drops."
    verdict = cassette.get("judge/calibration", lambda: faithfulness(judge(), issue, invented))
    assert verdict["score"] < THRESHOLD, verdict["reason"]
