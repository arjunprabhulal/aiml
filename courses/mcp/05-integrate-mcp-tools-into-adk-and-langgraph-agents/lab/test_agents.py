"""Replay the recorded model turns through both agents, offline, against the real MCP server.

Run: python -m unittest -v test_agents.py
The model is replaced by its recorded turns; the MCP server, adapters and agent loops are real.
TASKS_SERVER_PYTHON (or AIML_MCP_PYTHON) must point at a Python with mcp 2.3.0 installed.
"""
import asyncio
import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("TASKS_SERVER_PYTHON", os.environ.get("AIML_MCP_PYTHON", ""))

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.tools import ToolException  # noqa: E402
from langchain_mcp_adapters.tools import load_mcp_tools  # noqa: E402

import agent_adk  # noqa: E402
import agent_langgraph  # noqa: E402
import record_runs  # noqa: E402

HERE = Path(__file__).resolve().parent
RECORD = json.loads((HERE / "agent-runs.json").read_text(encoding="utf-8"))


def recorded(framework, question):
    """The first recorded trial, which the replay tests reproduce."""
    run = next(run for run in RECORD["runs"] if run["framework"] == framework and run["question"] == question)
    return run["trials"][0]


class ReplayLlm(BaseLlm):
    """An ADK model that answers with the recorded turns, in order."""
    turns: list

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


class ReplayChatModel(GenericFakeChatModel):
    """A LangChain chat model that answers with the recorded turns, in order."""

    def bind_tools(self, tools, **kwargs):
        return self


def replay_adk(question):
    agent = agent_adk.root_agent.clone(update={"model": ReplayLlm(model="replay", turns=list(recorded("adk", question)["model_turns"]))})
    return record_runs.printed(agent_adk.show, asyncio.run(agent_adk.ask(question, agent)))


def replay_langgraph(question):
    turns = recorded("langgraph", question)["model_turns"]
    messages = iter([AIMessage(content=t["content"], tool_calls=[{**c, "id": f"call-{i}-{j}"} for j, c in enumerate(t["tool_calls"])])
                     for i, t in enumerate(turns)])
    return record_runs.printed(agent_langgraph.show, asyncio.run(agent_langgraph.ask(question, ReplayChatModel(messages=messages))))


class AgentReplay(unittest.TestCase):
    def test_adk_agent_resolves_a_task_name_to_its_id(self):
        transcript = replay_adk("Close the docs task.")
        self.assertEqual(transcript, recorded("adk", "Close the docs task.")["transcript"])
        self.assertIn("call   complete_task {'task_id': 'T-3'}", transcript)

    def test_langgraph_agent_resolves_a_task_name_to_its_id(self):
        transcript = replay_langgraph("Close the docs task.")
        self.assertEqual(transcript, recorded("langgraph", "Close the docs task.")["transcript"])
        self.assertIn("call   complete_task {'task_id': 'T-3'}", transcript)

    def test_adk_returns_a_tool_error_to_the_model(self):
        transcript = replay_adk("Mark task T-9 as done.")
        self.assertEqual(transcript, recorded("adk", "Mark task T-9 as done.")["transcript"])
        self.assertIn("result error Error executing tool complete_task: No task with ID T-9.", transcript)

    def test_langgraph_returns_a_tool_error_to_the_model(self):
        transcript = replay_langgraph("Mark task T-9 as done.")
        self.assertEqual(transcript, recorded("langgraph", "Mark task T-9 as done.")["transcript"])
        self.assertIn("result error Error executing tool complete_task: No task with ID T-9.", transcript)

    def test_get_tools_starts_a_new_server_session_for_each_call(self):
        async def add_then_list():
            tools = {tool.name: tool for tool in await agent_langgraph.client.get_tools()}
            await tools["add_task"].ainvoke({"title": "Tag v1.2"})
            return await tools["list_tasks"].ainvoke({})

        self.assertNotIn("Tag v1.2", str(asyncio.run(add_then_list())))

    def test_one_session_keeps_server_state_between_calls(self):
        async def add_then_list():
            async with agent_langgraph.client.session("tasks") as session:
                tools = {tool.name: tool for tool in await load_mcp_tools(session)}
                await tools["add_task"].ainvoke({"title": "Tag v1.2"})
                return await tools["list_tasks"].ainvoke({})

        self.assertIn("Tag v1.2", str(asyncio.run(add_then_list())))

    def test_langgraph_without_error_handling_raises_instead(self):
        async def call_unknown_task():
            async with agent_langgraph.client.session("tasks") as session:
                tools = {tool.name: tool for tool in await load_mcp_tools(session, handle_tool_errors=False)}
                try:
                    await tools["complete_task"].ainvoke({"task_id": "T-9"})
                except ToolException as error:
                    return error

        self.assertIn("No task with ID T-9", str(asyncio.run(call_unknown_task())))

    def test_both_frameworks_discover_the_recorded_tools(self):
        for name, module in [("adk", agent_adk), ("langgraph", agent_langgraph)]:
            self.assertEqual(record_runs.printed(lambda: asyncio.run(module.discover())), RECORD["discovery"][name])

    def test_every_recorded_trial_reached_the_expected_outcome(self):
        for run in RECORD["runs"]:
            for trial in run["trials"]:
                calls = trial["calls"]
                if run["question"] == "Close the docs task.":
                    done = calls.index("complete_task {'task_id': 'T-3'}")
                    self.assertTrue(calls[done + 1].startswith(("ok", "success")), calls)
                else:
                    self.assertEqual(calls[0], "complete_task {'task_id': 'T-9'}")
                    self.assertTrue(calls[1].startswith("error Error executing tool complete_task: No task with ID T-9"))

    def test_agent_server_is_the_typed_tools_lesson_server(self):
        first = (HERE.parent / "mcp-typed-tools" / "tasks_server.py").read_bytes()
        self.assertEqual((HERE / "tasks_server.py").read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
