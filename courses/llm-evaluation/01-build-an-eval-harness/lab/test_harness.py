"""Failure cases for the harness itself. No model call; runs offline."""
import json

import pytest
from pydantic import ValidationError

from harness import Cassette, Dataset, RecordingError, load_dataset

CASE = {"id": "a", "issue": "text", "expected": {"label": "bug"}}


def dataset(*cases):
    return Dataset.model_validate({"name": "t", "version": 1, "cases": list(cases)})


def test_duplicate_case_id_is_rejected():
    with pytest.raises(ValidationError, match="duplicate case id: a"):
        dataset(CASE, CASE)


def test_unknown_label_is_rejected():
    with pytest.raises(ValidationError, match="label"):
        dataset({**CASE, "expected": {"label": "bugg"}})


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError, match="must_mentoin"):
        dataset({**CASE, "must_mentoin": ["sync"]})


def test_edited_case_changes_the_dataset_sha():
    original = dataset(CASE)
    edited = dataset({**CASE, "issue": "text, edited"})
    assert original.version == edited.version
    assert original.sha != edited.sha


def test_stale_recording_is_refused(tmp_path):
    path = tmp_path / "tape.json"
    tape = Cassette(path, {"dataset_sha": dataset(CASE).sha, "model": "m"}, live=True)
    tape.get("triage/a", lambda: "{}")
    tape.save()
    edited = dataset({**CASE, "issue": "text, edited"})
    with pytest.raises(RecordingError, match="dataset_sha changed"):
        Cassette(path, {"dataset_sha": edited.sha, "model": "m"}, live=False)


def test_missing_recording_entry_is_an_error(tmp_path):
    path = tmp_path / "tape.json"
    path.write_text(json.dumps({"key": {"model": "m"}, "entries": {}}))
    tape = Cassette(path, {"model": "m"}, live=False)
    with pytest.raises(RecordingError, match="no entry 'triage/a'"):
        tape.get("triage/a", lambda: "{}")


def test_replay_without_a_recording_asks_for_live(tmp_path):
    with pytest.raises(RecordingError, match="run pytest --live"):
        Cassette(tmp_path / "absent.json", {"model": "m"}, live=False)


def test_shipped_dataset_is_valid():
    assert len(load_dataset().cases) > 0


def test_replay_reproduces_the_recorded_run(tmp_path):
    """Replaying the cassette gives the same outcome for every test as the live run."""
    import subprocess
    import sys
    from pathlib import Path

    here = Path(__file__).parent
    out = tmp_path / "replay.json"
    subprocess.run([sys.executable, "-m", "pytest", "-q", "test_triage.py", "--json-report",
                    f"--json-report-file={out}"], cwd=here, capture_output=True)
    outcomes = lambda path: {t["nodeid"]: t["outcome"] for t in json.loads(path.read_text())["tests"]}  # noqa: E731
    assert outcomes(out) == outcomes(here / "runs" / "gemini-3.8-flash-v1.json")
