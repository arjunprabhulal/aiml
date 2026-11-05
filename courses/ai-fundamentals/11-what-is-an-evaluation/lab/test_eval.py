"""Unit tests for the grader, and checks on the recorded eval run. Run: python -m pytest -q"""
import json
from pathlib import Path

from assistant import DocsAnswer, DocsAnswerV2
from run_eval import CASES, grade

RUNS = json.loads(Path(__file__).with_name("results.json").read_text())
CASE = {c["id"]: c for c in CASES}


def test_a_correct_answer_passes_even_with_backticks_and_case_changes():
    answer = DocsAnswer(answer="Run `DOCUCTL ROLLBACK --env production --to r41`.", source="rollback.md")
    assert grade(CASE["rollback-command"], answer) == []


def test_the_command_field_counts_toward_the_required_phrases():
    answer = DocsAnswer(answer="Use the rollback command.", source="rollback.md", command="docuctl rollback --to <release>")
    assert grade(CASE["revert-replaced"], answer) == []


def test_a_wrong_source_and_a_missing_phrase_are_both_reported():
    answer = DocsAnswer(answer="It was removed in 2.0.", source="deploy.md")
    assert grade(CASE["revert-replaced"], answer) == ["cited deploy.md, expected rollback.md", "missing 'docuctl rollback'"]


def test_only_version_2_can_say_no_page_covers_the_question():
    assert DocsAnswerV2(answer="The docs do not cover it.", source=None).source is None
    assert "null" not in json.dumps(DocsAnswer.model_json_schema()["properties"]["source"])


def test_every_version_ran_every_case_three_times():
    for run in RUNS.values():
        assert sorted(r["case"] for r in run["results"]) == sorted(c["id"] for c in CASES for _ in range(3))


def test_neither_fix_made_the_not_in_docs_case_pass():
    assert [run["passed"]["not-in-docs"] for run in RUNS.values()] == [0, 0, 0]
    assert all(run["passed"]["revert-replaced"] == 0 for run in RUNS.values())


def test_fresh_eval_leaves_original_recording_unchanged(tmp_path, monkeypatch):
    import run_eval as app
    original = tmp_path / "results.json"
    original.write_text("original recording")
    monkeypatch.setattr(app, "HERE", tmp_path)
    monkeypatch.setattr(app.ollama, "Client", lambda: object())
    monkeypatch.setattr(app, "run_case", lambda _client, case, *_args: {"case": case["id"], "passed": False, "problems": []})
    app.main()
    assert original.read_text() == "original recording"
    current = json.loads((tmp_path / "runs/local-docuctl/results.json").read_text())
    assert len(current) == 3
    assert all(len(run["results"]) == 3 * len(app.CASES) for run in current.values())
