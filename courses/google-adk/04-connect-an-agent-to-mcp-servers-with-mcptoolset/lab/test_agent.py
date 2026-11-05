"""Replay the recorded Gemini turns against the real MCP server, offline.

Run: TASKS_SERVER_PYTHON=/path/to/python-with-mcp-2 python -m unittest -v test_agent.py
The model is replaced by its recorded turns; McpToolset, the stdio server and the agent loop are real.
"""
import asyncio
import json
import logging
import os
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
if os.environ.get("AIML_MCP_PYTHON"):
    os.environ.setdefault("TASKS_SERVER_PYTHON", os.environ["AIML_MCP_PYTHON"])

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

import agent  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
BAD = "/no/such/python"


class ReplayLlm(BaseLlm):
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def replay(turns: list, toolset=None, model_id="replay") -> tuple[str, ReplayLlm]:
    model = ReplayLlm(model=model_id, turns=list(turns), requests=[])
    events = asyncio.run(agent.ask("replayed question", agent.build_agent(model, toolset)))
    return agent.show(events), model


def offered(model: ReplayLlm) -> list[str]:
    return sorted(d.name for t in model.requests[0].config.tools for d in t.function_declarations)


from output_cap_check import assert_capped_wire

class McpToolsetTests(unittest.TestCase):

    def test_every_tool_turn_keeps_the_serialized_response_cap(self):
        _, model = replay(RECORD["runs"]["add"]["model_turns"], model_id=agent.MODEL)
        self.assertGreater(len(model.requests), 1)
        assert_capped_wire(self, model.requests)
        for request in model.requests:
            sent = request.config.model_dump(mode="json", by_alias=True, exclude_none=True)
            self.assertEqual(sent["maxOutputTokens"], 1024)


    def test_tool_filter_hides_complete_task(self):
        self.assertEqual(sorted(asyncio.run(agent.list_tools())), sorted(RECORD["discovery"]))
        self.assertIn("complete_task", RECORD["unfiltered"])
        self.assertNotIn("complete_task", RECORD["discovery"])

    def test_the_agent_adds_a_task_on_the_real_server(self):
        run = RECORD["runs"]["add"]
        transcript, _ = replay(run["model_turns"])
        self.assertEqual(transcript, run["transcript"])
        self.assertIn("result add_task isError=False {'id': 'T-4'", transcript)

    def test_a_filtered_tool_is_never_offered_to_the_model(self):
        _, model = replay(RECORD["runs"]["filtered"]["model_turns"])
        self.assertEqual(offered(model), ["add_task", "list_tasks", "read_page"])

    def test_server_tool_descriptions_are_fenced_as_untrusted(self):
        description = RECORD["declarations"]["add_task"]["description"]
        self.assertTrue(description.startswith("<<<BEGIN_UNTRUSTED_TOOL_DESCRIPTION>>>"))
        _, model = replay(RECORD["runs"]["filtered"]["model_turns"])
        sent = {d.name: d for t in model.requests[0].config.tools for d in t.function_declarations}
        self.assertEqual(sent["add_task"].description, description)
        self.assertIn("were supplied by the tool's own server", model.requests[0].config.system_instruction)

    def test_a_server_that_cannot_start_leaves_the_agent_without_its_tools(self):
        answer = RECORD["failures"]["bad_command"]["transcript"].removeprefix("answer ")
        transcript, model = replay([{"role": "model", "parts": [{"text": answer}]}], agent.tracker(python=BAD))
        self.assertEqual(offered(model), ["read_page"])  # no error reaches the caller
        self.assertEqual(transcript, RECORD["failures"]["bad_command"]["transcript"])

    def test_discovery_at_startup_fails_loudly(self):
        toolset = agent.tracker(python=BAD)
        with self.assertRaises(ConnectionError):
            asyncio.run(toolset.get_tools())
        asyncio.run(toolset.close())


if __name__ == "__main__":
    unittest.main()
