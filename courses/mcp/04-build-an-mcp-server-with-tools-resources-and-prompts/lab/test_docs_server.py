"""Tests for docs_server.py: python -m unittest -v test_docs_server.py"""
import asyncio
import json
import sys
import unittest
from pathlib import Path

import jsonschema
from mcp import Client, MCPError, StdioServerParameters
from mcp.server import MCPServer

import inspect_server

HERE = Path(__file__).resolve().parent


class Primitives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = asyncio.run(inspect_server.collect())

    def test_lists_one_tool_resource_template_and_prompt(self):
        r = self.r
        self.assertEqual([t["name"] for t in r["tools/list"]["tools"]], ["search_docs"])
        self.assertEqual([x["uri"] for x in r["resources/list"]["resources"]], ["docs://index"])
        self.assertEqual([x["uriTemplate"] for x in r["resources/templates/list"]["resourceTemplates"]], ["docs://pages/{slug}"])
        prompt = r["prompts/list"]["prompts"][0]
        self.assertEqual([(a["name"], a.get("required", False)) for a in prompt["arguments"]], [("slug", True), ("focus", False)])

    def test_search_output_matches_its_output_schema(self):
        tool, result = self.r["tools/list"]["tools"][0], self.r["search worker"]["result"]
        jsonschema.validate(result["structuredContent"], tool["outputSchema"])
        self.assertEqual([hit["slug"] for hit in result["structuredContent"]["result"]], ["quickstart", "configuration"])
        self.assertEqual(tool["annotations"], {"readOnlyHint": True, "openWorldHint": False})

    def test_empty_query_is_a_tool_error(self):
        result = self.r["search empty query"]["result"]
        self.assertIs(result["isError"], True)
        self.assertIn("The query is empty.", result["content"][0]["text"])

    def test_template_reads_one_page_as_markdown(self):
        content = self.r["read page"]["result"]["contents"][0]
        self.assertEqual((content["uri"], content["mimeType"]), ("docs://pages/retries", "text/markdown"))
        self.assertTrue(content["text"].startswith("# Retries"))
        index = json.loads(self.r["read index"]["result"]["contents"][0]["text"])
        self.assertEqual([page["slug"] for page in index], ["quickstart", "configuration", "retries"])

    def test_missing_page_is_invalid_params_not_empty_contents(self):
        self.assertEqual(self.r["read missing page"]["error"], {"code": -32602, "message": "No docs page named scheduling."})

    def test_unmatched_uri_is_invalid_params(self):
        self.assertEqual(self.r["read unmatched URI"]["error"]["code"], -32602)

    def test_prompt_embeds_the_page_and_uses_the_default_focus(self):
        first, second = self.r["get prompt"]["result"]["messages"]
        self.assertEqual(first["content"]["type"], "resource")
        self.assertEqual(first["content"]["resource"]["uri"], "docs://pages/retries")
        self.assertEqual(second["content"]["text"], "Review this docs page for accuracy. List each problem with the sentence it is in.")

    def test_prompt_mistakes_are_invalid_params(self):
        self.assertEqual(self.r["get prompt without slug"]["error"], {"code": -32602, "message": "Missing required arguments: slug"})
        self.assertEqual(self.r["get unknown prompt"]["error"]["code"], -32602)
        self.assertEqual(self.r["get prompt for a missing page"]["error"]["code"], -32602)

    def test_saved_results_match_a_fresh_run(self):
        self.assertEqual(json.loads((HERE / "primitives-results.json").read_text()), self.r)


class PlainSdkDefault(unittest.TestCase):
    def test_plain_server_reports_prompt_mistakes_as_internal_errors(self):
        """Why DocsServer overrides get_prompt: mcp 2.3.0 answers these with -32603."""
        plain = MCPServer("plain")

        @plain.prompt()
        def greet(name: str) -> str:
            return f"Say hello to {name}."

        async def codes():
            found = []
            async with Client(plain) as client:
                for name in ("greet", "nope"):
                    try:
                        await client.get_prompt(name, {})
                    except MCPError as error:
                        found.append(error.error.code)
            return found

        with self.assertLogs("mcp", level="ERROR"):
            self.assertEqual(asyncio.run(codes()), [-32603, -32603])


class OverStdio(unittest.TestCase):
    def test_server_runs_as_a_stdio_subprocess(self):
        async def session():
            params = StdioServerParameters(command=sys.executable, args=[str(HERE / "docs_server.py")])
            async with Client(params) as client:
                page = await client.read_resource("docs://pages/quickstart")
                return page.contents[0].mime_type

        self.assertEqual(asyncio.run(session()), "text/markdown")


if __name__ == "__main__":
    unittest.main()
