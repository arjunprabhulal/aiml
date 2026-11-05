"""Robustness suite: every case under every perturbation, then adversarial cases."""
import pytest

from conftest import ADVERSARIAL, DATASET
from perturb import PERTURBATIONS

cases = pytest.mark.parametrize("case", DATASET.cases, ids=lambda c: c.id)


@cases
def test_original(case, run_triage):
    assert run_triage(f"original/{case.id}", case.issue).label == case.expected.label


@cases
@pytest.mark.parametrize("perturbation", PERTURBATIONS)
def test_label_survives(case, perturbation, run_triage):
    text = PERTURBATIONS[perturbation](case.issue)
    assert text != case.issue, "perturbation left the issue unchanged"
    assert run_triage(f"{perturbation}/{case.id}", text).label == case.expected.label


@pytest.mark.parametrize("case", ADVERSARIAL.cases, ids=lambda c: c.id)
def test_adversarial(case, run_triage):
    result = run_triage(f"adversarial/{case.id}", case.issue)
    assert result.label == case.expected.label
    if case.expected.priority:
        assert result.priority == case.expected.priority
