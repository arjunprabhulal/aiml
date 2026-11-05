"""Offline tests: the tools are real, the model is a scripted fake. Run: python -m pytest -q"""
import json
from types import SimpleNamespace

from docs_tools import answer, definition, read_page, run_tool, search_docs


def call(name, **arguments):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


class ScriptedModel:
    """Replies with the scripted tool calls in order, then with a final text answer."""
    def __init__(self, *turns):
        self.turns, self.seen = list(turns), []

    def chat(self, messages, **_):
        self.seen.append(list(messages))
        calls = self.turns.pop(0) if self.turns else None
        return SimpleNamespace(message=SimpleNamespace(tool_calls=calls, content="final answer [rollback.md]"))


def test_the_model_sees_the_allowed_pages_as_an_enum():
    page = definition(read_page)["function"]["parameters"]["properties"]["page"]
    assert page["enum"] == ["config.md", "deploy.md", "rollback.md", "tokens.md"]


def test_search_returns_only_pages_that_match():
    assert [hit["page"] for hit in search_docs("rollback")] == ["rollback.md"]


def test_a_tool_result_goes_back_to_the_model_before_it_answers():
    model = ScriptedModel([call("read_page", page="rollback.md")])
    log = answer(model, "q")
    tool_message = model.seen[1][-1]
    assert tool_message["role"] == "tool" and "docuctl rollback" in json.loads(tool_message["content"])
    assert log[-1] == "answer: final answer [rollback.md]"


def test_an_invalid_argument_becomes_an_error_result():
    assert run_tool("read_page", {"page": "secrets.md"}).startswith("error: invalid arguments for read_page")


def test_a_tool_that_was_not_offered_is_never_run():
    assert run_tool("delete_page", {"page": "rollback.md"}) == "error: unknown tool 'delete_page'; available tools: search_docs, read_page"


def test_the_round_limit_stops_a_model_that_keeps_calling_tools():
    model = ScriptedModel(*[[call("search_docs", query="rollback")]] * 5)
    assert answer(model, "q", max_rounds=2)[-1] == "stopped: no answer after 2 rounds"


def test_request_specific_filter_refuses_a_known_but_unoffered_tool():
    assert run_tool("read_page", {"page": "rollback.md"}, {"search_docs"}).startswith("error: tool")


def test_a_single_response_does_not_start_an_agent_loop():
    from single_call import call_once
    model = ScriptedModel([call("read_page", page="rollback.md")])
    results = call_once(model, "q")
    assert len(model.seen) == 1
    assert results[0]["name"] == "read_page" and "docuctl rollback" in results[0]["result"]


def test_an_empty_offered_list_executes_nothing():
    from single_call import call_once
    model = ScriptedModel([call("read_page", page="rollback.md")])
    results = call_once(model, "q", tools=[])
    assert results[0]["result"].startswith("error: tool")


def test_callable_tools_still_use_the_offered_name_check():
    model = ScriptedModel([call("read_page", page="rollback.md")])
    log = answer(model, "q", tools=[read_page])
    assert "docuctl rollback" in model.seen[1][-1]["content"]
    assert log[-1] == "answer: final answer [rollback.md]"
