"""Replay actual model chunks; execute the sample tools and pytest for real."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from harness.loop import agent_events
from harness.tools import RepoTools

HERE = Path(__file__).resolve().parent


def comparable(messages):
    result = copy.deepcopy(messages)
    for message in result:
        if message.get("role") == "tool" and message.get("tool_name") == "run_tests":
            value = json.loads(message["content"])
            # Fresh pytest output has its own elapsed time and temporary paths.
            message["content"] = {key: value.get(key) for key in ("exit_code", "error")}
    return result


@pytest.mark.parametrize("filename,expected_stop,expected_exit", [
    ("recorded-run.json", "assistant_finished", 0),
    ("recorded-max-turns.json", "max_turns", 1),
])
def test_saved_model_turns_replay_through_real_tools(tmp_path, filename, expected_stop, expected_exit):
    record = json.loads((HERE / filename).read_text())
    work = tmp_path / "repo"
    shutil.copytree(HERE / "sample_repo", work)
    tools = RepoTools(work)
    test_bytes = (work / "tests/test_path_rules.py").read_bytes()
    assert hashlib.sha256(test_bytes).hexdigest() == record["tests_sha256"]
    assert tools.run_tests()["exit_code"] == record["before"]["exit_code"] == 1
    turns = iter(record["turns"])
    consumed = []
    def replay(messages, schemas):
        turn = next(turns)
        assert comparable(messages) == comparable(turn["messages"])
        consumed.append(turn)
        yield from copy.deepcopy(turn["chunks"])
    events = list(agent_events(replay, tools, record["task"], record["max_turns"]))
    assert len(consumed) == len(record["turns"])
    assert events[-1]["reason"] == record["events"][-1]["reason"] == expected_stop
    assert tools.run_tests()["exit_code"] == record["after"]["exit_code"] == expected_exit
    assert (work / "path_rules.py").read_text() == record["result_source"]
    assert (work / "tests/test_path_rules.py").read_bytes() == test_bytes


def test_a_truncated_saved_stream_cannot_dispatch_its_tool(tmp_path):
    record = json.loads((HERE / "recorded-run.json").read_text())
    work = tmp_path / "repo"
    shutil.copytree(HERE / "sample_repo", work)
    chunks = copy.deepcopy(record["turns"][0]["chunks"])
    for chunk in chunks:
        chunk["done"] = False
        chunk.pop("done_reason", None)
    events = list(agent_events(lambda messages, schemas: iter(chunks), RepoTools(work), record["task"]))
    assert events[-1]["reason"] == "incomplete_model_turn"
    assert not any(event["type"].startswith("tool_") for event in events)
