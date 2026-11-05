"""Recorder reset and dedicated output directory checks, using no provider requests."""
import runpy
import sys
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
import langchain_google_genai

import record


def test_recorder_refuses_to_delete_existing_data_without_explicit_reset(tmp_path, monkeypatch):
    (tmp_path / "out").mkdir()
    note = tmp_path / "out/keep.md"
    note.write_text("Keep my earlier output.")
    checkpoint = tmp_path / "checkpoints.db"
    checkpoint.write_bytes(b"previous checkpoint bytes")
    monkeypatch.setattr(record, "HERE", tmp_path)
    monkeypatch.setattr(record.subprocess, "run", lambda *a, **k: pytest.fail("No process may start before reset consent."))
    with pytest.raises(SystemExit, match="--reset-example-data"):
        record.main()
    assert note.read_text() == "Keep my earlier output."
    assert checkpoint.read_bytes() == b"previous checkpoint bytes"


def test_explicit_reset_keeps_unrelated_files(tmp_path, monkeypatch):
    (tmp_path / "out").mkdir()
    (tmp_path / "out/old.md").write_text("old generated output")
    (tmp_path / "checkpoints.db").write_bytes(b"old generated checkpoint")
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("user notes")
    monkeypatch.setattr(record, "HERE", tmp_path)
    class StopBeforeAnyProvider(Exception):
        pass
    def stop(*a, **k):
        raise StopBeforeAnyProvider()
    monkeypatch.setattr(record.subprocess, "run", stop)
    with pytest.raises(StopBeforeAnyProvider):
        record.main(reset_example_data=True)
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "checkpoints.db").exists()
    assert unrelated.read_text() == "user notes"


def test_reset_flag_defaults_off():
    assert record.parse_args([]).reset_example_data is False
    assert record.parse_args(["--reset-example-data"]).reset_example_data is True


def test_direct_workflow_writes_only_to_the_selected_work_directory(tmp_path, monkeypatch):
    source = Path(record.__file__).with_name("workflow.py")
    protected = {p: p.read_bytes() if p.exists() else None
                 for p in [source.with_name("checkpoints.db"), source.parent / "out/announcements.log"]}
    fake = GenericFakeChatModel(messages=iter([AIMessage("- #412 Retry webhook delivery on503")]))
    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", lambda **kw: fake)
    run_dir = tmp_path / "my-run"
    monkeypatch.delenv("CRASH_AT", raising=False)
    monkeypatch.setattr(sys, "argv", [str(source), "--thread", "learner", "--version", "2.5.0",
                                      "--work-dir", str(run_dir)])
    runpy.run_path(str(source), run_name="__main__")
    assert (run_dir / "checkpoints.db").is_file()
    assert (run_dir / "out/2.5.0.md").read_text().startswith("# Release 2.5.0")
    assert (run_dir / "out/announcements.log").read_text() == "Released 2.5.0: out/2.5.0.md\n"
    for path, previous in protected.items():
        assert (path.read_bytes() if path.exists() else None) == previous
