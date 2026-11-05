"""Contract and failure tests for tasks_server.py. Run: python -m unittest -v test_tasks_server.py"""
import asyncio
import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from jsonschema import validate
from mcp import Client, types
from mcp.shared.exceptions import MCPError

import record
import tasks_server

HERE = Path(__file__).resolve().parent


class TypedTools(unittest.TestCase):
    def setUp(self):
        self.module = importlib.reload(tasks_server)  # a fresh in-memory task list for every test

    def run_client(self, work):
        async def main():
            async with Client(self.module.server) as client:
                return await work(client)
        return asyncio.run(main())

    def call(self, name, arguments):
        return self.run_client(lambda client: client.call_tool(name, arguments))

    def test_tools_publish_input_and_output_schemas(self):
        tools = {tool.name: tool for tool in self.run_client(lambda client: client.list_tools()).tools}
        self.assertEqual(list(tools), ["list_tasks", "add_task", "complete_task"])
        self.assertEqual(tools["add_task"].input_schema["properties"]["title"]["minLength"], 3)
        self.assertEqual(tools["complete_task"].input_schema["properties"]["task_id"]["pattern"], r"^T-\d+$")
        self.assertEqual(tools["list_tasks"].output_schema["title"], "TaskList")

    def test_structured_content_matches_the_output_schema(self):
        tools = {tool.name: tool for tool in self.run_client(lambda client: client.list_tools()).tools}
        for name, arguments in [("list_tasks", {"status": "open"}), ("add_task", {"title": "Tag v1.2"})]:
            result = self.call(name, arguments)
            self.assertFalse(result.is_error)
            validate(result.structured_content, tools[name].output_schema)
            self.assertEqual(json.loads(result.content[0].text), result.structured_content)

    def test_invalid_arguments_are_rejected_before_the_tool_runs(self):
        for name, arguments, message in [
            ("add_task", {"title": "v2"}, "String should have at least 3 characters"),
            ("add_task", {"title": "Tag v1.2", "priority": "urgent"}, "Input should be 'low', 'normal' or 'high'"),
            ("complete_task", {"task_id": "3"}, "String should match pattern"),
        ]:
            result = self.call(name, arguments)
            self.assertTrue(result.is_error)
            self.assertIn(message, result.content[0].text)
        self.assertEqual(len(self.module.TASKS), 3)

    def test_unknown_task_id_is_a_tool_error_and_the_server_keeps_running(self):
        async def work(client):
            return await client.call_tool("complete_task", {"task_id": "T-9"}), await client.call_tool("list_tasks", {})
        failed, listed = self.run_client(work)
        self.assertTrue(failed.is_error)
        self.assertIn("No task with ID T-9. Call list_tasks", failed.content[0].text)
        self.assertEqual(listed.structured_content["count"], 3)

    def test_unknown_tool_name_is_a_tool_error_in_this_sdk(self):
        result = self.call("delete_task", {"task_id": "T-1"})
        self.assertTrue(result.is_error)
        self.assertEqual(result.content[0].text, "Unknown tool: delete_task")

    def test_unexpected_exception_hides_its_details(self):
        self.module.TASKS["T-2"] = None  # a corrupt record makes list_tasks raise AttributeError
        with self.assertLogs("mcp.server.mcpserver.server", "ERROR"):
            result = self.call("list_tasks", {})
        self.assertTrue(result.is_error)
        self.assertEqual(result.content[0].text, "Error executing tool list_tasks")

    def test_malformed_request_is_a_protocol_error(self):
        async def work(client):
            try:
                await client.session.send_request(types.Request(method="tools/call", params={"arguments": {}}), types.CallToolResult)
            except MCPError as error:
                return error
        error = self.run_client(work)
        self.assertIsInstance(error, MCPError)
        self.assertEqual(error.code, types.INVALID_PARAMS)

    def test_client_script_prints_the_recorded_output(self):
        run = subprocess.run([sys.executable, "client.py"], cwd=HERE, capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(run.stdout, (HERE / "client-output.txt").read_text(encoding="utf-8"))

    def test_saved_calls_match_a_fresh_run(self):
        saved = json.loads((HERE / "recorded-calls.json").read_text(encoding="utf-8"))
        self.assertEqual(asyncio.run(record.collect()), saved)


if __name__ == "__main__":
    unittest.main()
