"""Offline tests: a scripted model replaces Gemini, and a raised exception stands in for the crash."""
import json
import sqlite3
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver

import workflow

RUN = json.loads(Path(__file__).with_name("runs.json").read_text())


class Crash(Exception):
    pass


class Counting(GenericFakeChatModel):
    calls: int = 0

    def invoke(self, *args, **kwargs):
        self.calls += 1
        return super().invoke(*args, **kwargs)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "OUT", tmp_path / "out")
    model = Counting(messages=iter([AIMessage("- Retry webhook delivery on 503 (#412)")] * 5))
    saver = SqliteSaver(sqlite3.connect(tmp_path / "checkpoints.db", check_same_thread=False))
    return workflow.build_graph(saver, model), model, tmp_path / "out"


def crash_once(monkeypatch, node):
    """Make the next call of `node` raise, as a crash at that point would."""
    armed = [True]

    def point(name):
        if name == node and armed.pop():
            raise Crash(node)
    monkeypatch.setattr(workflow, "crash_point", lambda name: point(name) if armed else None)


def cfg(thread):
    return {"configurable": {"thread_id": thread}}


def test_a_resumed_run_skips_the_steps_already_checkpointed(setup, monkeypatch):
    graph, model, out = setup
    for update in graph.stream({"version": "2.5.0"}, cfg("t"), stream_mode="updates", durability="sync"):
        if "summarize" in update:
            break  # the process stops here, after summarize was checkpointed
    assert graph.get_state(cfg("t")).next == ("write_file",)
    graph.invoke(None, cfg("t"), durability="sync")
    assert model.calls == 1
    assert (out / "2.5.0.md").read_text().startswith("# Release 2.5.0")


def test_a_step_interrupted_after_its_side_effect_repeats_it(setup, monkeypatch):
    graph, model, out = setup
    crash_once(monkeypatch, "announce")
    with pytest.raises(Crash):
        graph.invoke({"version": "2.5.1"}, cfg("t"), durability="sync")
    graph.invoke(None, cfg("t"), durability="sync")
    assert (out / "announcements.log").read_text().count("Released 2.5.1") == 2


def test_a_new_thread_id_starts_over_and_calls_the_model_again(setup, monkeypatch):
    graph, model, out = setup
    crash_once(monkeypatch, "announce")
    with pytest.raises(Crash):
        graph.invoke({"version": "2.5.2"}, cfg("t"), durability="sync")
    graph.invoke({"version": "2.5.2"}, cfg("t-retry"), durability="sync")
    assert model.calls == 2


def test_resuming_a_finished_thread_does_nothing(setup):
    graph, model, out = setup
    graph.invoke({"version": "2.5.0"}, cfg("t"), durability="sync")
    assert graph.get_state(cfg("t")).next == ()
    graph.invoke(None, cfg("t"), durability="sync")
    assert model.calls == 1


def test_recorded_runs_resume_and_duplicate_as_described():
    by_name = {s["name"]: s["processes"] for s in RUN["scenarios"]}
    assert by_name["crash between steps, then resume"][1]["output"][0] == "resuming r1 at write_file"
    assert RUN["announcements"].count("Released 2.5.1: out/2.5.1.md") == 2
    assert "resuming" not in " ".join(by_name["durability exit, then a crash"][1]["output"])


@pytest.mark.parametrize("status", [200, 429])
def test_gemini_serialized_request_has_output_cap_and_no_retry(status, monkeypatch):
    """Exercise the installed SDK serializer and HTTP retry path without a provider."""
    import httpx
    from langchain_google_genai import ChatGoogleGenerativeAI

    requests = []
    def handle(request):
        assert request.method == "POST"
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path == "/v1beta/models/gemini-3.8-flash:generateContent"
        body = json.loads(request.content)
        assert body["generationConfig"]["maxOutputTokens"] == 1024
        assert "tools" not in body
        requests.append(body)
        if status == 429:
            return httpx.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                                       "message": "Offline retry check"}}, request=request)
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": "- Offline serializer check only (#412)"}]}, "finishReason": "STOP"}]}, request=request)

    def client(**kwargs):
        model = ChatGoogleGenerativeAI(**kwargs, api_key="OFFLINE-NON-CREDENTIAL-PLACEHOLDER",
                                      vertexai=False, client_args={"transport": httpx.MockTransport(handle),
                                                                  "trust_env": False})
        assert model.max_retries == 0
        assert model.timeout == 30
        return model

    monkeypatch.setattr(workflow, "MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(workflow, "ChatGoogleGenerativeAI", client)
    if status == 429:
        with pytest.raises(Exception):
            workflow.chat_model().invoke("Offline serializer and retry check")
    else:
        assert workflow.chat_model().invoke("Offline serializer and retry check").text.startswith("- Offline")
    assert len(requests) == 1
