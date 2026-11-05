"""Test the MCP server in memory: the real MCP protocol, with a counting model instead of Gemini.

Run: python -m unittest -v test_server.py
"""
import asyncio
import json
import logging
import os
import unittest
import warnings
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.tools.mcp_tool import StdioConnectionParams, to_mcp_server  # noqa: E402
from google.genai import types  # noqa: E402
from mcp import McpError, StdioServerParameters  # noqa: E402
from mcp.shared.memory import create_connected_server_and_client_session as connect  # noqa: E402

import server  # noqa: E402
import release_bot  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))


class CountingLlm(BaseLlm):
    """Answers with the number of developer messages in the request, after an optional delay."""
    delay: float = 0.0

    async def generate_content_async(self, llm_request, stream=False):
        await asyncio.sleep(self.delay)
        seen = sum(1 for c in llm_request.contents if c.role == "user" and any(p.text for p in c.parts))
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=f"messages seen: {seen}")]))


def serve(model) -> object:
    return to_mcp_server(server.root_agent.clone(update={"model": model}))


def run(coro):
    return asyncio.run(coro)


class AgentAsMcpServer(unittest.TestCase):
    def test_the_server_offers_one_tool_that_takes_a_request(self):
        async def go():
            async with connect(serve(CountingLlm(model="count"))) as client:
                return (await client.list_tools()).tools
        tools = run(go())
        self.assertEqual([t.name for t in tools], ["docuctl_docs"])
        self.assertEqual(tools[0].inputSchema["required"], ["request"])
        self.assertEqual(tools[0].description, server.root_agent.description)

    def test_calls_on_one_connection_share_a_session(self):
        mcp_server = serve(CountingLlm(model="count"))

        async def go():
            async with connect(mcp_server) as first:
                a = await first.call_tool("docuctl_docs", {"request": "one"})
                b = await first.call_tool("docuctl_docs", {"request": "two"})
            async with connect(mcp_server) as second:
                c = await second.call_tool("docuctl_docs", {"request": "three"})
            return [r.content[0].text for r in (a, b, c)]
        self.assertEqual(run(go()), ["messages seen: 1", "messages seen: 2", "messages seen: 1"])

    def test_an_agent_error_comes_back_as_an_error_result(self):
        saved = {k: os.environ.pop(k) for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY") if k in os.environ}
        try:
            async def go():
                async with connect(serve("gemini-3.8-flash")) as client:
                    return await client.call_tool("docuctl_docs", {"request": "How do I roll back?"})
            result = run(go())
        finally:
            os.environ.update(saved)
        self.assertTrue(result.isError)
        self.assertIn("No API key was provided", result.content[0].text)

    def test_a_slow_agent_exceeds_the_client_read_timeout(self):
        async def go():
            async with connect(serve(CountingLlm(model="count", delay=1.0)),
                               read_timeout_seconds=timedelta(seconds=0.2)) as client:
                try:
                    await client.call_tool("docuctl_docs", {"request": "slow"})
                except McpError as error:
                    return str(error)
        self.assertIn("Timed out while waiting for response", run(go()))

    def test_stdio_connections_default_to_a_five_second_timeout(self):
        params = StdioConnectionParams(server_params=StdioServerParameters(command="python"))
        self.assertEqual(params.timeout, 5.0)
        errors = [r for r in RECORD["failures"]["default_timeout"]["results"] if "error" in r]
        self.assertIn("Waited 5.0 seconds", errors[0]["error"])


class ClientCleanup(unittest.TestCase):
    def test_a_failed_run_closes_the_runner_and_toolset(self):
        async def failing_run(**kwargs):
            raise RuntimeError("transport failed")
            yield  # keep the Runner.run_async interface

        runner = MagicMock()
        runner.run_async = failing_run
        runner.close = AsyncMock()
        toolset = MagicMock()
        toolset.close = AsyncMock()
        with patch.object(release_bot, "docs_toolset", return_value=toolset), \
             patch.object(release_bot, "make_bot"), patch.object(release_bot, "Runner", return_value=runner):
            with self.assertRaisesRegex(RuntimeError, "transport failed"):
                run(release_bot.ask("Read the rollback page."))
        runner.close.assert_awaited_once()
        toolset.close.assert_awaited_once()


class RecordedRun(unittest.TestCase):
    """Checks on the recorded Gemini run: these read recorded-runs.json and make no model call."""

    def test_the_follow_up_on_the_same_connection_answered_for_1x(self):
        same, fresh = RECORD["same_connection"]["calls"][1]["text"], RECORD["new_connection"]["calls"][0]["text"]
        self.assertIn("docuctl release list", same)
        self.assertNotIn("1.x", fresh)

    def test_the_server_without_the_key_failed_every_call(self):
        self.assertTrue(all(c["is_error"] for c in RECORD["failures"]["no_key"]["calls"]))


if __name__ == "__main__":
    unittest.main()
