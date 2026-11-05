"""Offline tests: a scripted planner and executor replace Gemini; the checks run on real files."""
import json
from itertools import count
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

import graph
from workspace import make_tools

TASK = json.loads(Path(__file__).with_name("task.json").read_text())
RUN = json.loads(Path(__file__).with_name("runs.json").read_text())
FIXED = TASK["files"]["client/http.py"].replace("= 30", "= 10").replace(
    "base_url: str):", "base_url: str, timeout=DEFAULT_TIMEOUT):").replace("= DEFAULT_TIMEOUT\n", "= timeout\n")
CHANGELOG = TASK["files"]["CHANGELOG.md"].replace("## Unreleased\n", "## Unreleased\n- #415 Add a per-client timeout override\n")
PLAN = graph.Plan(steps=[graph.Step(path="client/http.py", change="fix"), graph.Step(path="CHANGELOG.md", change="add")])
ids = count()


class Scripted(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def write(path, content):
    return AIMessage("", tool_calls=[{"name": "write_file", "args": {"path": path, "content": content}, "id": f"w{next(ids)}"}])


def run(tmp_path, replies, plans=None):
    prompts = []
    planner = RunnableLambda(lambda prompt: prompts.append(prompt) or PLAN)
    g = graph.build_graph(Scripted(messages=iter(replies)), step_limit=8, planner=planner)
    return graph.run_task(g, TASK, tmp_path), prompts


def test_a_correct_edit_passes_every_check(tmp_path):
    state, _ = run(tmp_path, [write("client/http.py", FIXED), AIMessage("Fixed http.py."),
                              write("CHANGELOG.md", CHANGELOG), AIMessage("Added the line.")])
    assert state["verdict"] == "pass" and state["attempt"] == 1


def test_the_verdict_comes_from_the_files_not_the_report(tmp_path):
    claims = [AIMessage("Done: DEFAULT_TIMEOUT is 10 and Client takes a timeout.")] * 4
    state, _ = run(tmp_path, claims)
    assert state["verdict"] == "fail"
    assert all("Done" in e["report"] for e in state["log"])


def test_editing_the_tests_to_pass_fails_the_unchanged_check(tmp_path):
    easier = TASK["files"]["tests/test_client.py"].replace("== 10", "== 30")
    replies = [write("tests/test_client.py", easier), AIMessage("Tests pass now."), write("CHANGELOG.md", CHANGELOG), AIMessage("ok")] * 2
    state, _ = run(tmp_path, replies)
    by_kind = {("pytest" if r.get("pytest") else "unchanged" if r.get("unchanged") else r["contains"]): r["passed"]
               for r in state["results"]}
    assert state["verdict"] == "fail" and by_kind["unchanged"] is False


def test_the_failed_checks_go_into_the_next_plan(tmp_path):
    state, prompts = run(tmp_path, [AIMessage("nothing")] * 4)
    assert state["attempt"] == graph.MAX_ATTEMPTS
    assert "failed these checks" not in prompts[0] and '"pytest": true' in prompts[1]


def test_an_executor_that_runs_out_of_steps_still_reaches_verify(tmp_path):
    reads = (AIMessage("", tool_calls=[{"name": "read_file", "args": {"path": "CHANGELOG.md"}, "id": f"r{n}"}]) for n in count())
    state, _ = run(tmp_path, reads)
    assert state["results"] and state["verdict"] == "fail"
    assert "stopped at the step limit" in state["log"][-1]["report"]


def test_the_checks_are_not_hidden_from_the_model(tmp_path):
    # The verdict is the verifier's, but the checks are not secret: the test file the pytest check runs is in the
    # workspace the executor reads. test_the_failed_checks_go_into_the_next_plan covers the replanning prompt.
    for name, text in TASK["files"].items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    read_file, _ = make_tools(tmp_path)
    pytest_check = next(c for c in TASK["checks"] if c.get("pytest"))
    assert read_file.invoke({"path": pytest_check["path"]}) == TASK["files"][pytest_check["path"]]


def test_a_path_outside_the_workspace_is_refused(tmp_path):
    read_file, write_file = make_tools(tmp_path)
    assert write_file.invoke({"path": "../escape.txt", "content": "x"}).startswith("Refused")
    assert not (tmp_path.parent / "escape.txt").exists()


def test_recorded_runs_failed_at_8_steps_and_passed_at_16():
    short, full = RUN["runs"]
    assert (short["step_limit"], short["verdict"], short["attempts"]) == (8, "fail", 2)
    assert (full["step_limit"], full["verdict"]) == (graph.STEP_LIMIT, "pass")
