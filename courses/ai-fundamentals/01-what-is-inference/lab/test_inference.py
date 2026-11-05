"""Offline tests: a fake client stands in for Ollama. Run: python -m pytest -q"""
from types import SimpleNamespace

import ollama
import pytest

from inference import DOCS, QUESTION, ask, describe


class FakeClient:
    def __init__(self):
        self.requests = []

    def chat(self, **request):
        self.requests.append(request)
        return SimpleNamespace(message=SimpleNamespace(content=" an answer \n"))

    def show(self, model):
        if model != "gemma4:e2b":
            raise ollama.ResponseError(f"model '{model}' not found", 404)
        return SimpleNamespace(details=SimpleNamespace(family="gemma4", parameter_size="4.6B", quantization_level="Q4_K_M"),
                               modelinfo={"gemma4.context_length": 131072})


def test_describe_reads_the_context_length_for_the_family():
    assert describe(FakeClient()) == {"family": "gemma4", "parameters": "4.6B", "quantization": "Q4_K_M", "context_length": 131072}


def test_without_a_page_only_the_question_is_sent():
    client = FakeClient()
    assert ask(client, QUESTION) == "an answer"
    assert client.requests[0]["messages"] == [{"role": "user", "content": QUESTION}]


def test_the_page_travels_in_the_prompt():
    client = FakeClient()
    page = (DOCS / "rollback.md").read_text()
    ask(client, QUESTION, page)
    prompt = client.requests[0]["messages"][0]["content"]
    assert page in prompt and prompt.endswith(QUESTION)


def test_requests_are_repeatable():
    client = FakeClient()
    ask(client, QUESTION)
    assert client.requests[0]["options"] == {"temperature": 0, "seed": 7}
    assert client.requests[0]["think"] is False


def test_a_model_that_is_not_pulled_raises_404():
    with pytest.raises(ollama.ResponseError) as error:
        describe(FakeClient(), "gemma4:e4b")
    assert error.value.status_code == 404


def test_the_recorded_run_shows_the_invented_and_the_grounded_answer():
    output = (DOCS.parent / "run-output.txt").read_text()
    without, grounded = output.split("--- with docs/rollback.md in the prompt")
    assert "document" in without and "revision" in without
    assert "release named r41" in grounded and "does not rebuild" in grounded
