"""Offline tests for the review agent. A scripted chat model replaces Gemma, so no Ollama is needed."""
import json
from itertools import count
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

import record
import review_queue
from graph import TOOLS, build_graph

ids = count()


class ScriptedChat(GenericFakeChatModel):
    """Returns the scripted messages in order; tool binding is a no-op."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(*calls):
    return AIMessage("", tool_calls=[{"name": n, "args": a, "id": f"c{next(ids)}"} for n, a in calls])


def run(script, limit=12, **options):
    graph = build_graph(ScriptedChat(messages=iter(script)), **options)
    path, state = [], None
    for kind, data in graph.stream({"messages": [HumanMessage("q")]}, {"recursion_limit": limit},
                                   stream_mode=["updates", "values"]):
        if kind == "updates":
            path += list(data)
        else:
            state = data
    return path, state["messages"]


def test_a_reply_without_tool_calls_ends_the_run():
    path, messages = run([AIMessage("Nothing to look up.")])
    assert path == ["agent"]


def test_tool_results_go_back_to_the_agent():
    path, messages = run([call(("get_diff", {"number": 415})), AIMessage("It raises the timeout.")])
    assert path == ["agent", "tools", "agent"]
    assert messages[2].content == review_queue.PULL_REQUESTS[415]["diff"]


def test_parallel_tool_calls_run_in_one_tools_step():
    path, messages = run([call(("get_diff", {"number": 418}), ("get_ci_status", {"number": 418})), AIMessage("Done.")])
    assert path == ["agent", "tools", "agent"]
    asked = [c["id"] for c in messages[1].tool_calls]
    assert [m.tool_call_id for m in messages[2:4]] == asked
    assert messages[3].content == "passed"


def test_unknown_pull_request_becomes_an_error_tool_message():
    path, messages = run([call(("get_ci_status", {"number": 999})), AIMessage("No such pull request.")])
    assert path == ["agent", "tools", "agent"]
    assert messages[2].status == "error" and "no open pull request #999" in messages[2].content


def test_default_tool_errors_stop_the_run():
    with pytest.raises(review_queue.UnknownPullRequest):
        run([call(("get_ci_status", {"number": 999}))], catch_unknown_pr=False)
    recorded = record.run(build_graph(ScriptedChat(messages=iter([call(("get_ci_status", {"number": 999}))])),
                                      catch_unknown_pr=False), "q")
    assert recorded["error"].startswith("UnknownPullRequest")
    assert recorded["path"] == ["agent"] and recorded["graph_steps"] == 1  # failed tools node emitted no update


def test_invalid_arguments_become_an_error_tool_message_by_default():
    path, messages = run([call(("get_diff", {"number": "four-fifteen"})), AIMessage("Retrying.")],
                         catch_unknown_pr=False)
    assert messages[2].status == "error" and "number" in messages[2].content


def test_endless_tool_calls_hit_the_recursion_limit():
    endless = (call(("list_open_prs", {})) for _ in count())
    with pytest.raises(GraphRecursionError):
        run(endless, limit=6)


def test_recorded_tool_results_match_the_queue():
    record = json.loads((Path(__file__).parent / "runs.json").read_text())
    tools = {t.name: t for t in TOOLS}
    for r in record["runs"]:
        calls = [c for s in r["steps"] if "tool_calls" in s for c in s["tool_calls"]]
        results = [t for s in r["steps"] if s["node"] == "tools" for t in s["results"]]
        assert r["graph_steps"] == len(r["path"]) and r["tool_calls"] == len(calls)
        for c, result in zip(calls, results):
            if result["status"] == "success":
                out = tools[c["name"]].invoke(c["args"])
                assert result["content"] == (out if isinstance(out, str) else json.dumps(out))


def test_the_record_counts_steps_tool_calls_and_messages_separately():
    two_calls = call(("get_diff", {"number": 418}), ("get_ci_status", {"number": 418}))
    r = record.run(build_graph(ScriptedChat(messages=iter([two_calls, AIMessage("Done.")]))), "q")
    assert r["path"] == ["agent", "tools", "agent"]  # two ToolMessages, one tools step
    assert (r["graph_steps"], r["model_calls"], r["tool_calls"], r["messages"]) == (3, 2, 2, 5)
    assert [t["tool"] for t in r["steps"][1]["results"]] == ["get_diff", "get_ci_status"]


def test_the_step_limit_counts_graph_steps_not_messages():
    def three_steps(limit):
        two_calls = call(("get_diff", {"number": 418}), ("get_ci_status", {"number": 418}))
        return record.run(build_graph(ScriptedChat(messages=iter([two_calls, AIMessage("Done.")]))), "q", limit=limit)
    r = three_steps(4)  # 3 graph steps and 5 messages finish within a limit of 4
    assert r["error"] is None and (r["graph_steps"], r["messages"]) == (3, 5)
    r = three_steps(3)  # a run of N steps needs a limit of at least N + 1
    assert r["error"].startswith("GraphRecursionError") and r["graph_steps"] == 3
    r = three_steps(2)
    assert r["error"].startswith("GraphRecursionError") and r["path"] == ["agent", "tools"]
