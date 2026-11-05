"""Tests for the CI triage graph's limits. A scripted chat model replaces Gemini, so no network or API key is needed."""
import asyncio
import time

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage

import ci
import graph


class ScriptedChat(GenericFakeChatModel):
    delay: float = 0.0

    def bind_tools(self, tools, **kwargs):
        return self

    async def _agenerate(self, *args, **kwargs):
        await asyncio.sleep(self.delay)
        return self._generate(*args, **kwargs)


def reply(tokens, **call):
    calls = [{"name": call.pop("name"), "args": call, "id": f"c{tokens}"}] if call else []
    return AIMessage("" if calls else "answer", tool_calls=calls,
                     usage_metadata={"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens})


def triage(messages, delay=0.0, **limits):
    model = ScriptedChat(messages=iter(messages), delay=delay)
    return asyncio.run(graph.triage(graph.build_graph(model, **limits), "Why is CI failing on pull request 421?"))


def test_a_slow_tool_becomes_a_tool_message_and_the_run_goes_on(monkeypatch):
    monkeypatch.setattr(ci, "TOOL_TIMEOUT", 0.2)
    started = time.perf_counter()
    result = triage([reply(100, name="fetch_job_log", job_id=815), reply(100)])
    tool = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert "did not finish within 0.2s" in tool.content
    assert result["messages"][-1].content == "answer"
    assert time.perf_counter() - started < 2  # the 8 s call was cancelled


def test_a_fast_tool_returns_its_result():
    result = triage([reply(100, name="fetch_job_log", job_id=812), reply(100)])
    tool = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool.content.startswith("FAILED tests/test_client.py")


def test_the_token_budget_stops_the_run_before_more_tools_run():
    result = triage([reply(500, name="list_failed_jobs", pr=415),
                     reply(400, name="fetch_job_log", job_id=812)], token_budget=800)
    assert result["stop_reason"] == "token_budget" and result["tokens"] == 900
    assert sum(isinstance(m, ToolMessage) for m in result["messages"]) == 1


def test_the_budget_is_checked_between_calls_so_one_call_can_overshoot_it():
    result = triage([reply(500, name="list_failed_jobs", pr=415), reply(700)], token_budget=800)
    assert "stop_reason" not in result and result["tokens"] == 1200


def test_a_slow_model_call_ends_the_run_at_its_timeout():
    started = time.perf_counter()
    result = triage([reply(100)], delay=5.0, model_timeout=0.3)
    assert result["stop_reason"] == "model_timeout"
    assert "exceeded its run timeout of 0.300s" in result["messages"][-1].content
    assert time.perf_counter() - started < 2


def test_other_tool_errors_are_not_hidden_from_the_caller(monkeypatch):
    monkeypatch.setitem(ci.JOBS, 900, {"pr": 415, "name": "lint", "delay": "soon", "log": ""})
    with pytest.raises(TypeError):
        triage([reply(100, name="fetch_job_log", job_id=900), reply(100)])


@pytest.mark.parametrize("usage", [None, {}, {"total_tokens": None}, {"total_tokens": "100"},
                                   {"total_tokens": -1}, {"total_tokens": True}, {"total_tokens": 1.5}])
def test_missing_or_invalid_usage_stops_before_tools_and_keeps_known_subtotal(usage):
    # model_copy lets this adapter-boundary test represent malformed provider metadata.
    unknown = reply(1, name="fetch_job_log", job_id=812).model_copy(update={"usage_metadata": usage})
    result = triage([reply(120, name="list_failed_jobs", pr=415), unknown])
    assert result["stop_reason"] == "missing_usage"
    assert result["usage_known"] is False and result["tokens"] == 120
    assert sum(isinstance(m, ToolMessage) for m in result["messages"]) == 1
    assert "120" in result["messages"][-1].content and "known subtotal" in result["messages"][-1].content


def test_missing_usage_on_an_answer_is_not_reported_as_a_measured_zero():
    unknown = AIMessage("An answer without provider usage.")
    result = triage([unknown])
    assert result["stop_reason"] == "missing_usage"
    assert result["usage_known"] is False
    assert "known subtotal" in result["messages"][-1].content
    assert "unknown" in result["messages"][-1].content


def test_reported_zero_tokens_is_distinct_from_missing_usage():
    result = triage([reply(0)])
    assert result["usage_known"] is True and result["tokens"] == 0
    assert "stop_reason" not in result


def test_a_timeout_after_reported_usage_marks_the_run_total_unknown():
    class SlowSecondReply(ScriptedChat):
        calls: int = 0

        async def _agenerate(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                await asyncio.sleep(5)
            return self._generate(*args, **kwargs)

    model = SlowSecondReply(messages=iter([reply(120, name="list_failed_jobs", pr=415)]))
    result = asyncio.run(graph.triage(graph.build_graph(model, model_timeout=0.3), "Check CI."))
    assert result["stop_reason"] == "model_timeout"
    assert result["tokens"] == 120 and result["usage_known"] is False
    assert sum(isinstance(m, ToolMessage) for m in result["messages"]) == 1
