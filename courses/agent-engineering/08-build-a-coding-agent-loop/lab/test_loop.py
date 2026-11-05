"""Offline checks exercise the actual loop and sample tools, without a model."""
import copy
import json
from pathlib import Path
import shutil

import pytest

from harness.loop import agent_events
from harness.tools import RepoTools

HERE = Path(__file__).resolve().parent


def response(text="", calls=None, done=True, reason="stop"):
    message = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = calls
    return {"message": message, "done": done, "done_reason": reason}


def call(name, **arguments):
    return {"function": {"name": name, "arguments": arguments}}


@pytest.fixture
def tools(tmp_path):
    work = tmp_path / "repo"
    shutil.copytree(HERE / "sample_repo", work)
    return RepoTools(work)


def test_tools_run_the_real_failing_then_repaired_repo(tools):
    assert tools.run_tests()["exit_code"] == 1
    result = tools.replace_text('PurePosixPath(name)', 'PurePosixPath(name.replace("\\\\", "/"))')
    assert result["replaced"] == 1
    assert tools.run_tests()["exit_code"] == 0


def test_streamed_tool_call_and_result_are_in_the_next_request(tools):
    requests = []
    def chat(messages, schemas):
        requests.append(copy.deepcopy(messages))
        if len(requests) == 1:
            yield response("Inspecting ", done=False)
            yield response("the file.", [call("read_file", path="path_rules.py")])
        else:
            assistant, result = messages[-2:]
            assert assistant["content"] == "Inspecting the file."
            assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
            assert result["role"] == "tool" and result["tool_name"] == "read_file"
            assert "def python_sources" in json.loads(result["content"])["text"]
            yield response("Read complete.")
    events = list(agent_events(chat, tools, "Inspect the sample"))
    assert events[-1]["reason"] == "assistant_finished"
    assert [e["text"] for e in events if e["type"] == "text_delta"] == ["Inspecting ", "the file.", "Read complete."]
    assert len(requests) == 2


def test_max_turns_stops_a_model_that_keeps_calling_tools(tools):
    requests = []
    def chat(messages, schemas):
        requests.append(copy.deepcopy(messages))
        yield response(calls=[call("read_file", path="path_rules.py")])
    events = list(agent_events(chat, tools, "Keep reading", max_turns=2))
    assert len(requests) == 2
    assert events[-1] == {"type": "stopped", "turn": 2, "reason": "max_turns"}
    assert len([e for e in events if e["type"] == "tool_result"]) == 2


@pytest.mark.parametrize("reason,done", [(None, False), ("length", True)])
def test_incomplete_model_turn_does_not_execute_a_tool(tools, reason, done):
    before = (tools.root / "path_rules.py").read_bytes()
    def chat(messages, schemas):
        yield response(calls=[call("replace_text", old="PurePosixPath(name)", new="broken")], done=done, reason=reason)
    events = list(agent_events(chat, tools, "Inspect"))
    assert events[-1]["reason"] == "incomplete_model_turn"
    assert not [e for e in events if e["type"].startswith("tool_")]
    assert (tools.root / "path_rules.py").read_bytes() == before


def test_unknown_tool_returns_an_error_message_without_dispatch(tools):
    seen = []
    def chat(messages, schemas):
        seen.append(copy.deepcopy(messages))
        if len(seen) == 1:
            yield response(calls=[call("run_shell", command="echo unimplemented")])
        else:
            assert json.loads(messages[-1]["content"])["error"] == "unknown tool: run_shell"
            yield response("The tool is unavailable.")
    events = list(agent_events(chat, tools, "Inspect"))
    assert events[-1]["reason"] == "assistant_finished"
    assert len(seen) == 2


def test_nonzero_test_exit_is_tool_data_not_model_completion(tools):
    def chat(messages, schemas):
        yield response(calls=[call("run_tests")])
    events = list(agent_events(chat, tools, "Check", max_turns=1))
    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["result"]["exit_code"] == 1
    assert events[-1]["reason"] == "max_turns"


def test_final_message_does_not_claim_the_repository_passes(tools):
    def chat(messages, schemas):
        yield response("All fixed.")
    events = list(agent_events(chat, tools, "Fix"))
    assert events[-1]["reason"] == "assistant_finished"
    assert tools.run_tests()["exit_code"] == 1


def test_two_tool_calls_receive_two_results_in_order(tools):
    seen = []
    def chat(messages, schemas):
        seen.append(copy.deepcopy(messages))
        if len(seen) == 1:
            yield response(calls=[call("read_file", path="path_rules.py"), call("run_tests")])
        else:
            assert [m["tool_name"] for m in messages[-2:]] == ["read_file", "run_tests"]
            yield response("The test fails.")
    assert list(agent_events(chat, tools, "Check"))[-1]["reason"] == "assistant_finished"


def test_model_transport_error_stops_with_no_tool_execution(tools):
    def chat(messages, schemas):
        raise ConnectionError("local model connection ended")
        yield
    events = list(agent_events(chat, tools, "Inspect"))
    assert events[-1]["reason"] == "model_error"
    assert "connection ended" in events[-1]["error"]


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_model_turn_budget_must_be_a_positive_integer(tools, budget):
    with pytest.raises(ValueError, match="positive integer"):
        list(agent_events(None, tools, "Inspect", budget))
