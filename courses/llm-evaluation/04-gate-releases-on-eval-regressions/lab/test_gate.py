"""Failure cases for the regression gate. No model call; runs offline."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gate import gate

HERE = Path(__file__).parent
POLICY = json.loads((HERE / "policy.json").read_text())
KEY = {"dataset": "issue-triage@1", "dataset_sha": "aaa", "model": "m", "prompt_version": "v1",
       "prompt_sha": "p1", "judge_model": "j"}


def run(outcomes: dict, **key) -> dict:
    tests = [{"nodeid": f"test_triage.py::{name}", "outcome": o} for name, o in outcomes.items()]
    return {"eval": {**KEY, **key}, "tests": tests}


BASE = {f"test_label[c{i}]": "passed" for i in range(20)} | {"test_priority[c0]": "passed"}


def test_changed_dataset_is_incomparable():
    result = gate(run(BASE), run(BASE, dataset_sha="bbb"), POLICY)
    assert result["decision"] == "incomparable" and "rerun the baseline" in result["reasons"][0]


def test_changed_judge_is_incomparable():
    assert gate(run(BASE), run(BASE, judge_model="other"), POLICY)["decision"] == "incomparable"


def test_one_regression_blocks():
    result = gate(run(BASE), run(BASE | {"test_label[c3]": "failed"}, prompt_version="v2"), POLICY)
    assert result["decision"] == "block"
    assert result["regressed"] == ["test_triage.py::test_label[c3]"]
    assert result["changed"] == {"prompt_version": ["v1", "v2"]}


def test_critical_failure_blocks_even_if_the_baseline_failed_it_too():
    both = BASE | {"test_priority[c0]": "failed"}
    result = gate(run(both), run(both), POLICY)
    assert result["decision"] == "block" and result["regressed"] == []
    assert result["critical_failures"] == ["test_triage.py::test_priority[c0]"]


def test_low_pass_rate_blocks_without_a_regression():
    weak = BASE | {f"test_label[c{i}]": "failed" for i in range(3)}
    result = gate(run(weak), run(weak), POLICY)
    assert result["decision"] == "block" and result["reasons"] == ["pass rate 0.857 is below 0.9"]


def test_test_missing_from_the_candidate_is_a_regression():
    fewer = {k: v for k, v in BASE.items() if k != "test_label[c5]"}
    assert gate(run(BASE), run(fewer), POLICY)["regressed"] == ["test_triage.py::test_label[c5]"]


def test_deleting_a_failing_critical_test_blocks():
    failing = BASE | {"test_priority[c0]": "failed"}
    deleted = {k: v for k, v in failing.items() if k != "test_priority[c0]"}
    result = gate(run(failing), run(deleted), POLICY)
    assert result["decision"] == "block" and result["regressed"] == []
    assert result["missing_critical"] == ["test_triage.py::test_priority[c0]"]
    assert result["reasons"] == ["1 critical test(s) from the baseline are missing from the candidate"]


def test_fix_without_regression_passes():
    result = gate(run(BASE | {"test_label[c1]": "failed"}), run(BASE), POLICY)
    assert result["decision"] == "pass" and result["fixed"] == ["test_triage.py::test_label[c1]"]


@pytest.mark.parametrize("candidate, code", [(BASE, 0), (BASE | {"test_label[c3]": "failed"}, 1), (None, 2)])
def test_exit_code_is_the_decision(tmp_path, candidate, code):
    (tmp_path / "b.json").write_text(json.dumps(run(BASE)))
    report = run(candidate) if candidate else run(BASE, dataset_sha="bbb")
    (tmp_path / "c.json").write_text(json.dumps(report))
    done = subprocess.run([sys.executable, str(HERE / "gate.py"), str(tmp_path / "b.json"), str(tmp_path / "c.json")],
                          capture_output=True, text=True)
    assert done.returncode == code, done.stdout


@pytest.mark.parametrize("baseline, candidate, decision", [
    ("baseline", "prompt-v2", "prompt-v2"),
    ("baseline", "gemma4-e2b", "gemma4-e2b"),
    ("baseline", "prompt-v2-dataset-v2", "prompt-v2-dataset-v2"),
    ("baseline-dataset-v2", "prompt-v2-dataset-v2", "prompt-v2-on-dataset-v2"),
])
def test_recorded_decisions_reproduce(baseline, candidate, decision):
    load = lambda name: json.loads((HERE / "runs" / f"{name}.json").read_text())  # noqa: E731
    assert gate(load(baseline), load(candidate), POLICY) == load(f"gate-{decision}")
