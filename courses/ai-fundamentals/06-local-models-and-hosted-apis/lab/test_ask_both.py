"""Offline tests: both clients are replaced, so no key and no server are needed. Run: python -m pytest -q"""
import ast
from pathlib import Path
from types import SimpleNamespace

import ask_both

RECORDED = [ast.literal_eval(line) for line in Path(__file__).with_name("run-output.txt").read_text().splitlines()]


def test_local_and_hosted_get_the_same_instructions_and_question(monkeypatch):
    sent = {}

    def fake_chat(model, think, options, messages):
        sent["local"] = messages
        return SimpleNamespace(prompt_eval_count=1, eval_count=1, message=SimpleNamespace(content="a"))

    class FakeModels:
        def generate_content(self, model, contents, config):
            sent["hosted"] = (config.system_instruction, contents)
            usage = SimpleNamespace(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0)
            return SimpleNamespace(usage_metadata=usage, text="a")

    monkeypatch.setattr(ask_both.ollama, "chat", fake_chat)
    monkeypatch.setattr(ask_both.genai, "Client", lambda: SimpleNamespace(models=FakeModels()))
    ask_both.ask_local("q"), ask_both.ask_hosted("q")
    assert sent["local"] == [{"role": "system", "content": ask_both.SYSTEM}, {"role": "user", "content": "q"}]
    assert sent["hosted"] == (ask_both.SYSTEM, "q")


def test_both_recorded_answers_say_migrations_are_not_rolled_back():
    assert all("not rolled back" in run["answer"] for run in RECORDED)


def test_the_hosted_model_spent_hidden_thinking_tokens():
    hosted = next(run for run in RECORDED if run["where"].startswith("hosted"))
    assert hosted["thinking_tokens"] > hosted["output_tokens"]


def test_each_side_failed_for_its_own_reason():
    failures = Path(__file__).with_name("failures-output.txt").read_text()
    assert "No API key was provided" in failures and "Failed to connect to Ollama" in failures


def test_hosted_model_uses_environment_and_explicit_override(monkeypatch):
    selected = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            selected.append(model)
            usage = SimpleNamespace(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0)
            return SimpleNamespace(usage_metadata=usage, text="answer")

    monkeypatch.setattr(ask_both.genai, "Client", lambda: SimpleNamespace(models=FakeModels()))
    monkeypatch.setenv("GEMINI_MODEL", "environment-model")
    ask_both.ask_hosted("q")
    ask_both.ask_hosted("q", model="explicit-model")
    assert selected == ["environment-model", "explicit-model"]
