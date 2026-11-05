"""Failure cases for the evaluation code. Replays the recording; no model call."""
import json
from pathlib import Path

import pytest
from deepeval.models import GeminiModel

from cassette import Cassette, RecordingError
import evaluate as evaluate_module
from evaluate import evaluate, first_failure, recording_key, retrieval_scores, tool_scores

HERE = Path(__file__).parent
# ToolCorrectnessMetric compares names here and never calls this model; the key is a placeholder.
JUDGE = GeminiModel(model="gemini-3.8-flash", api_key="offline")


def calls(*names):
    return [{"name": n, "args": {}} for n in names]


def test_hit_and_reciprocal_rank():
    assert retrieval_scores(["init", "storage", "sync"], ["storage"]) == {"hit": True, "recall": 1.0, "reciprocal_rank": 0.5}
    assert retrieval_scores(["init", "sync", "tokens"], ["storage"]) == {"hit": False, "recall": 0.0, "reciprocal_rank": 0.0}


def test_hit_hides_a_missing_second_page_and_recall_shows_it():
    scores = retrieval_scores(["import", "output", "init"], ["output", "config"])
    assert scores["hit"] and scores["recall"] == 0.5


def test_case_without_expected_pages_skips_retrieval():
    assert retrieval_scores(["init"], []) is None


def test_extra_tool_call_scores_one_in_deepeval_but_fails_here():
    scores = tool_scores("q", calls("get_issue", "search_docs"), ["get_issue"], JUDGE)
    assert scores["score"] == 1.0
    assert scores["unexpected"] == ["search_docs"] and not scores["pass"]


def test_missing_tool_call_fails():
    assert tool_scores("q", calls("search_docs"), ["get_issue", "search_docs"], JUDGE)["score"] == 0.5


def test_tool_call_when_none_expected_fails():
    assert tool_scores("q", calls("search_docs"), [], JUDGE)["score"] == 0.0


def test_first_failing_stage_is_named():
    row = {"tools": {"pass": True}, "retrieval": {"hit": True, "recall": 0.5},
           "judged": {"faithfulness": {"score": 0.2}, "contextual_recall": {"score": 0.0}}}
    assert first_failure(row) == "retrieval"
    row["retrieval"]["recall"] = 1.0
    assert first_failure(row) == "faithfulness"


TAPE = HERE / "recordings" / "gemini-3.8-flash.json"


def test_stale_recording_is_refused():
    recorded = json.loads(TAPE.read_text())["key"]
    with pytest.raises(RecordingError, match="judge changed"):
        Cassette(TAPE, {**recorded, "judge": "gemma4:e2b"}, live=False)


HASHED = ("cases_sha", "docs_sha", "prompt_sha", "k")


def inputs() -> dict:
    return {name: json.loads((HERE / f"{name}.json").read_text()) for name in ("cases", "docs", "issues")}


def hashed_key(cases, docs, issues) -> dict:
    key = recording_key(cases, docs, issues)
    return {k: key[k] for k in HASHED}


@pytest.mark.parametrize("name", ["gemini-3.8-flash", "gemma4-e2b"])
def test_recording_is_keyed_to_the_current_inputs(name):
    recorded = json.loads((HERE / "recordings" / f"{name}.json").read_text())["key"]
    assert {k: recorded[k] for k in HASHED} == hashed_key(**inputs())


def edit_case(i):
    i["cases"]["cases"][0]["question"] += " Answer in French."


def edit_page(i):
    i["docs"][0]["text"] += " Deprecated."


def edit_issue(i):
    next(iter(i["issues"].values()))["state"] = "open"


@pytest.mark.parametrize("edit, field", [(edit_case, "cases_sha"), (edit_page, "docs_sha"), (edit_issue, "docs_sha")])
def test_edited_input_without_a_version_bump_makes_the_recording_stale(edit, field):
    edited = inputs()
    edit(edited)
    recorded = json.loads(TAPE.read_text())["key"]
    with pytest.raises(RecordingError, match=f"{field} changed"):
        Cassette(TAPE, {**recorded, **hashed_key(**edited)}, live=False)


def test_edited_prompt_makes_the_recording_stale(monkeypatch):
    monkeypatch.setattr(evaluate_module, "PROMPT", evaluate_module.PROMPT + "\nAlways cite the page id.")
    recorded = json.loads(TAPE.read_text())["key"]
    with pytest.raises(RecordingError, match="prompt_sha changed"):
        Cassette(TAPE, {**recorded, **hashed_key(**inputs())}, live=False)


def test_recording_with_a_field_the_code_no_longer_sends_is_stale():
    recorded = json.loads(TAPE.read_text())["key"]
    with pytest.raises(RecordingError, match="docs_sha changed"):
        Cassette(TAPE, {k: v for k, v in recorded.items() if k != "docs_sha"}, live=False)


@pytest.mark.parametrize("name", ["gemini-3.8-flash", "gemma4-e2b"])
def test_replay_reproduces_the_saved_report(name):
    tape = HERE / "recordings" / f"{name}.json"
    cassette = Cassette(tape, json.loads(tape.read_text())["key"], live=False)
    report = evaluate(json.loads((HERE / "cases.json").read_text()), cassette, judge=lambda: JUDGE)
    saved = json.loads((HERE / "runs" / f"{name}.json").read_text())
    assert report == saved
