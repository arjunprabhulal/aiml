"""Offline tests with the local Gemma tokenizer and the recorded Ollama counts.
Run: TOKENIZER_PATH=/path/to/gemma-tokenizer python -m pytest -q"""
import json
from pathlib import Path

import pytest

from count_tokens import SAMPLES, count, load, pieces


RECORDED = json.loads(Path(__file__).with_name("counts.json").read_text())


@pytest.fixture(scope="module")
def tokenizer():
    return load()


def test_local_counts_match_the_recording(tokenizer):
    assert {name: count(tokenizer, text) for name, text in SAMPLES.items()} == {n: r["local"] for n, r in RECORDED.items()}


def test_the_runtime_adds_exactly_one_bos_token_to_a_raw_prompt():
    assert all(row["gemma_raw"] == row["local"] + 1 for row in RECORDED.values())


def test_the_chat_template_adds_tokens_you_did_not_write():
    assert all(row["gemma_chat"] - row["gemma_raw"] >= 7 for row in RECORDED.values())


def test_another_model_counts_the_same_text_differently():
    assert any(row["qwen_raw"] != row["gemma_raw"] for row in RECORDED.values())


def test_word_count_is_not_a_token_estimate(tokenizer):
    assert len(SAMPLES["id"].split()) == 1 and count(tokenizer, SAMPLES["id"]) == 26


def test_pieces_decode_back_to_the_text(tokenizer):
    ids = [token_id for _, token_id in pieces(tokenizer, SAMPLES["config"])]
    assert tokenizer.decode(ids) == SAMPLES["config"]


def test_current_docuctl_counts_match_actual_local_tokenizer(tokenizer):
    current=json.loads(Path(__file__).with_name("runs").joinpath("current-docuctl/local-counts.json").read_text())
    assert current["execution_mode"]=="fresh-local-tokenizer-only-no-inference"
    for name,text in SAMPLES.items():
        assert current["samples"][name]["text"]==text
        assert count(tokenizer,text)==current["samples"][name]["local"]
        assert pieces(tokenizer,text)==[tuple(row) for row in current["samples"][name]["pieces"]]


def test_fresh_runtime_counts_leave_original_recording_unchanged(tmp_path, monkeypatch):
    import compare_runtime as app
    original = tmp_path / "counts.json"
    original.write_text("original recording")
    monkeypatch.setattr(app, "__file__", str(tmp_path / "compare_runtime.py"))
    monkeypatch.setattr(app, "SAMPLES", {"example": "text"})
    monkeypatch.setattr(app, "load", lambda: object())
    monkeypatch.setattr(app.ollama, "Client", lambda: object())
    monkeypatch.setattr(app, "count", lambda *_: 2)
    monkeypatch.setattr(app, "processed", lambda *_args, **_kwargs: 3)
    app.main()
    assert original.read_text() == "original recording"
    assert json.loads((tmp_path / "runs/local-docuctl/counts.json").read_text())["example"]["local"] == 2
