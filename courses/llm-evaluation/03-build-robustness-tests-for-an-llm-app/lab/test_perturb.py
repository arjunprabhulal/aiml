"""Failure cases for the perturbations and the summary. No model call; runs offline."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness import load_dataset
from perturb import CODE, PERTURBATIONS, typos
from summary import summarize

HERE = Path(__file__).parent
ISSUES = [case.issue for case in load_dataset(HERE / "dataset.json").cases]


@pytest.mark.parametrize("name", PERTURBATIONS)
def test_perturbations_are_deterministic(name):
    assert [PERTURBATIONS[name](t) for t in ISSUES] == [PERTURBATIONS[name](t) for t in ISSUES]


@pytest.mark.parametrize("name", PERTURBATIONS)
def test_code_spans_are_never_changed(name):
    for text in ISSUES:
        perturbed = PERTURBATIONS[name](text)
        assert all(span in perturbed for span in CODE.findall(text))


@pytest.mark.parametrize("name", PERTURBATIONS)
def test_every_perturbation_changes_every_issue(name):
    """A perturbation that returns the issue unchanged tests nothing; the first live run hit this with typos."""
    assert all(PERTURBATIONS[name](text) != text for text in ISSUES)


def test_typos_keep_short_words():
    assert typos("Is it ok to run?") == "Is it ok to run?"


def test_summary_reports_a_flip_only_when_the_original_passes():
    tests = [("test_original[a]", "passed"), ("test_original[b]", "failed"),
             ("test_label_survives[typos-a]", "failed"), ("test_label_survives[typos-b]", "failed")]
    report = {"tests": [{"nodeid": f"test_robustness.py::{n}", "outcome": o} for n, o in tests]}
    assert summarize(report) == {"groups": {"original": "1/2", "typos": "0/2"}, "flips": ["typos-a"]}


def test_replay_reproduces_the_recorded_run(tmp_path):
    out = tmp_path / "replay.json"
    subprocess.run([sys.executable, "-m", "pytest", "-q", "test_robustness.py", "--json-report",
                    f"--json-report-file={out}"], cwd=HERE, capture_output=True)
    outcomes = lambda path: {t["nodeid"]: t["outcome"] for t in json.loads(path.read_text())["tests"]}  # noqa: E731
    assert outcomes(out) == outcomes(HERE / "runs" / "gemini-3.8-flash-v1.json")
