"""Tests for the code-review agent graph. A scripted chat model replaces Gemini, so no network or API key is needed."""
from itertools import count

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

import graph


class ScriptedChat(GenericFakeChatModel):
    """Returns the scripted messages in order; tool binding is a no-op."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name, **args):
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"c{next(ids)}"}])


ids = count()


def endless_lookups():
    for n in count(1):
        yield call("get_diff", number=400 + n)  # a new number each time, so no call repeats


def run(messages, limit=graph.RECURSION_LIMIT):
    g = graph.build_graph(ScriptedChat(messages=iter(messages)))
    path = []
    state = None
    for update in g.stream({"messages": [HumanMessage("q")]}, {"recursion_limit": limit},
                           stream_mode=["updates", "values"]):
        kind, data = update
        if kind == "updates":
            path += list(data)
        else:
            state = data
    return path, state


def test_an_answer_ends_the_run():
    path, state = run([call("list_open_prs"), call("get_ci_status", number=415),
                       AIMessage("#415 fails test_default_timeout.")])
    assert path == ["agent", "tools", "agent", "tools", "agent"]
    assert "stop_reason" not in state
    assert "expected 10, got 30" in state["messages"][-2].content  # the tool result the model read


def test_the_same_call_twice_stops_before_it_runs_again():
    path, state = run([call("get_ci_status", number=415), call("get_ci_status", number=415)])
    assert path == ["agent", "tools", "agent", "stop"]
    assert state["stop_reason"] == "repeated_call"


def test_the_repeat_check_matches_exact_arguments_in_any_key_order():
    first = AIMessage("", tool_calls=[{"name": "get_diff", "args": {"number": 415, "path": "a.py"}, "id": "c-a"}])
    reordered = AIMessage("", tool_calls=[{"name": "get_diff", "args": {"path": "a.py", "number": 415}, "id": "c-b"}])
    as_text = AIMessage("", tool_calls=[{"name": "get_diff", "args": {"number": "415", "path": "a.py"}, "id": "c-c"}])
    state = {"messages": [HumanMessage("q"), first], "remaining_steps": 20}
    assert graph.stop_reason({**state, "messages": [*state["messages"], reordered]}) == "repeated_call"
    assert graph.stop_reason({**state, "messages": [*state["messages"], as_text]}) is None  # exact match only


@pytest.mark.parametrize("limit", range(3, 13))
def test_a_model_that_never_answers_stops_inside_the_limit(limit):
    path, state = run(endless_lookups(), limit)
    assert state["stop_reason"] == "step_limit" and path[-1] == "stop"
    assert len(path) < limit


def test_without_the_stop_branch_the_run_raises():
    plain = StateGraph(graph.State)
    llm = ScriptedChat(messages=endless_lookups())
    plain.add_node("agent", lambda s: {"messages": [llm.invoke(s["messages"])]})
    plain.add_node("tools", ToolNode(graph.TOOLS, handle_tool_errors=True))
    plain.add_edge(START, "agent")
    plain.add_conditional_edges("agent", tools_condition)
    plain.add_edge("tools", "agent")
    with pytest.raises(GraphRecursionError):
        plain.compile().invoke({"messages": [HumanMessage("q")]}, {"recursion_limit": 8})


def test_the_default_limit_is_far_above_a_useful_run():
    seen = []
    probe = StateGraph(graph.State)
    probe.add_node("look", lambda s: seen.append(s["remaining_steps"]) or {})
    probe.add_edge(START, "look")
    probe.add_edge("look", END)
    probe.compile().invoke({"messages": []})
    assert seen[0] > 10_000  # so set recursion_limit on every run
