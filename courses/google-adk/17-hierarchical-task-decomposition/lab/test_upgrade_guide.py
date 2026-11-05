"""Replay the recorded depth-2 tree, check the recorded trials, and drive budgets with a stub."""
import asyncio
import copy
import json
import logging
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path
from statistics import mean

from google.adk.agents.run_config import RunConfig
from google.adk.models import BaseLlm, LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk import Agent
from google.adk.tools import AgentTool, ToolContext
from google.genai import types

from harness import ReplayLlm, run
from upgrade_guide import DelegationLog, build_tree, build_workflow, check_sources, read_page

HERE = Path(__file__).parent
logging.getLogger("google_adk").setLevel(logging.CRITICAL)
RECORD = json.loads((HERE / "guide-run.json").read_text())
RUNS = {(r["max_depth"], r["trial"]): r for r in RECORD["runs"]}
GUIDE = "# Guide\n\n## Configuration\n1. Run `docuctl migrate`.\n\nSource: reference/config.md"


class StubLlm(BaseLlm):
    """Each agent calls its first tool once, then answers. Counts every model call in the tree."""
    calls: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        last = llm_request.contents[-1].parts[-1]
        tool = next(iter(llm_request.tools_dict), None)
        if last.function_response or tool is None:
            part = types.Part(text=GUIDE)
        else:
            args = {"query": "docuctl"} if tool == "search_docs" else {"request": "config"}
            part = types.Part(function_call=types.FunctionCall(name=tool, args=args))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


async def run_with(workflow, plugins=(), run_config=None):
    runner = InMemoryRunner(agent=workflow, app_name="docs_assistant", plugins=list(plugins))
    session = await runner.session_service.create_session(app_name="docs_assistant", user_id="dev")
    message = types.Content(role="user", parts=[types.Part(text=RECORD["input"])])
    async for _ in runner.run_async(user_id="dev", session_id=session.id, new_message=message,
                                    run_config=run_config):
        pass


class HierarchicalDecomposition(unittest.TestCase):
    def test_replay_matches_the_recorded_depth_2_run(self):
        recorded = RUNS[(2, 1)]
        log = DelegationLog()
        model = ReplayLlm(model=RECORD["environment"]["model"],
                          calls=copy.deepcopy(recorded["model_calls"]))
        events, _ = asyncio.run(run(build_workflow(model, max_depth=2), RECORD["input"],
                                    plugins=[log]))
        self.assertEqual(events, recorded["events"])
        self.assertEqual(sorted(map(json.dumps, log.rows)),
                         sorted(map(json.dumps, recorded["delegation"])))

    def test_no_trial_delegates_below_its_depth_limit(self):
        for recorded in RECORD["runs"]:
            depths = {row["depth"] for row in recorded["delegation"] if "depth" in row}
            self.assertEqual(max(depths), recorded["max_depth"])

    def test_the_leaf_can_read_but_not_delegate(self):
        leaf = build_tree("gemini-3.8-flash", max_depth=2).tools[0].agent
        self.assertEqual(leaf.name, "write_section")
        self.assertFalse(any(isinstance(tool, AgentTool) for tool in leaf.tools))

    def test_every_recorded_guide_cites_existing_pages(self):
        for recorded in RECORD["runs"]:
            if recorded.get("error"):
                self.assertIn("tree-wide model call budget of 24 exceeded", recorded["error"])
                self.assertLessEqual(len(recorded["model_calls"]), 24)
            else:
                check_sources(recorded["events"][-1]["message"])

    def test_the_deeper_tree_made_more_model_calls(self):
        calls = {d: mean(len(RUNS[(d, t)]["model_calls"]) for t in (1, 2, 3)) for d in (2, 3)}
        self.assertGreater(calls[3], calls[2])

    def test_each_planner_delegation_is_logged(self):
        recorded = RUNS[(2, 1)]
        asks = [row for row in recorded["delegation"] if row.get("calls") == "write_section"]
        proposed = [part["function_call"] for call in recorded["model_calls"]
                    for part in call["reply"].get("content", {}).get("parts", [])
                    if part.get("function_call", {}).get("name") == "write_section"]
        self.assertEqual(len(asks), len(proposed))
        self.assertGreaterEqual(len(asks), 2)

    def test_the_planner_can_delegate_a_section_twice(self):
        # Controlled model behavior, not an additional provider recording:
        # the real workflow admits two identical proposals from its planner.
        class RepeatingPlanner(BaseLlm):
            planner_calls: int = 0

            async def generate_content_async(self, llm_request, stream=False):
                if "write_section" in llm_request.tools_dict:
                    self.planner_calls += 1
                    if self.planner_calls <= 2:
                        part = types.Part(function_call=types.FunctionCall(
                            name="write_section", args={"request": "Write the configuration section."}))
                    else:
                        part = types.Part(text=GUIDE)
                else:
                    part = types.Part(text=GUIDE)
                yield LlmResponse(content=types.Content(role="model", parts=[part]))

        model = RepeatingPlanner(model="controlled-repeat-proposals")
        log = DelegationLog(max_model_calls=8)
        events, _ = asyncio.run(run(build_workflow(model, max_depth=2),
                                   "Write a configuration guide.", plugins=[log]))
        proposals = [row for row in log.rows if row.get("calls") == "write_section"]
        self.assertEqual(len(proposals), 2)
        self.assertEqual(proposals[0]["args"], proposals[1]["args"])
        self.assertEqual(sum(row.get("agent") == "write_section" and "depth" in row
                             for row in log.rows), 2)
        self.assertEqual(events[-1]["message"], GUIDE)
        self.assertEqual(GUIDE.count("\n## "), 1)

    def test_max_llm_calls_bounds_each_nested_run_not_the_tree(self):
        stub = StubLlm(model="stub")
        asyncio.run(run_with(build_workflow(stub, max_depth=3), run_config=RunConfig(max_llm_calls=2)))
        self.assertEqual(stub.calls, 6)  # two calls per level, three levels, no error

    def test_a_plugin_budget_stops_the_whole_tree(self):
        stub = StubLlm(model="stub")
        with self.assertRaisesRegex(RuntimeError, "tree-wide model call budget of 4 exceeded"):
            asyncio.run(run_with(build_workflow(stub, max_depth=3),
                                 plugins=[DelegationLog(max_model_calls=4)]))
        self.assertEqual(stub.calls, 4)

    def test_a_guide_that_cites_a_missing_page_is_refused(self):
        with self.assertRaisesRegex(ValueError, r"missing pages: \['guide/upgrade.md'\]"):
            check_sources(GUIDE.replace("reference/config.md", "guide/upgrade.md"))

    def test_agent_tool_forwards_child_state_to_the_parent(self):
        def write_state(tool_context: ToolContext):
            tool_context.state["child_marker"] = "written by leaf"
            return {"saved": True}

        class StateLlm(BaseLlm):
            async def generate_content_async(self, llm_request, stream=False):
                last = llm_request.contents[-1].parts[-1]
                if last.function_response:
                    part = types.Part(text="done")
                else:
                    tool = next(iter(llm_request.tools_dict))
                    args = {} if tool == "write_state" else {"request": "save marker"}
                    part = types.Part(function_call=types.FunctionCall(name=tool, args=args))
                yield LlmResponse(content=types.Content(role="model", parts=[part]))

        model = StateLlm(model="stub")
        leaf = Agent(name="leaf", model=model, tools=[write_state])
        parent = Agent(name="parent", model=model, tools=[AgentTool(leaf)])
        runner = InMemoryRunner(agent=parent, app_name="docs_assistant")

        async def go():
            _, session_id = await run(parent, "save marker", runner=runner)
            return await runner.session_service.get_session(
                app_name=runner.app_name, user_id="dev", session_id=session_id)

        self.assertEqual(asyncio.run(go()).state["child_marker"], "written by leaf")

    def test_a_guide_without_sections_is_refused(self):
        with self.assertRaises(ValueError):
            check_sources("Everything is upgraded.")

    def test_each_section_needs_its_own_final_source(self):
        bad = "# Guide\n\n## First\nNo citation.\n\n## Second\nSource: reference/config.md\nSource: reference/config.md"
        with self.assertRaises(ValueError):
            check_sources(bad)

    def test_a_source_outside_docs_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "outside.md").write_text("outside")
            with patch("upgrade_guide.DOCS", root / "docs"):
                with self.assertRaises(ValueError):
                    check_sources(GUIDE.replace("reference/config.md", "../outside.md"))

    def test_a_source_symlink_outside_docs_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "outside.md").write_text("outside")
            (root / "docs/link.md").symlink_to(root / "outside.md")
            with patch("upgrade_guide.DOCS", root / "docs"):
                with self.assertRaises(ValueError):
                    check_sources(GUIDE.replace("reference/config.md", "link.md"))

    def test_the_leaf_tool_cannot_read_outside_docs(self):
        self.assertEqual(read_page("../upgrade_guide.py"), {"error": "no docs page at ../upgrade_guide.py"})


if __name__ == "__main__":
    unittest.main()
