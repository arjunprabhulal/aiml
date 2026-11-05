"""Tests for the traced MCP client: python -m unittest -v test_traced_client.py"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import traced_client

HERE = Path(__file__).resolve().parent


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node["children"])


class TracedRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            cls.log, cls.tree = traced_client.run(directory)
        cls.calls = cls.log["docs"]["log"]
        cls.spans = list(walk(cls.tree["roots"]))
        cls.app = next(root for root in cls.tree["roots"] if root["name"] == "answer docs question")

    def test_discovery_records_version_server_and_capabilities(self):
        self.assertEqual(self.log["docs"]["discovery"], {"protocol_version": "2026-07-28", "server": "docs 1.0.0",
                                                         "capabilities": ["tools", "resources", "prompts"]})
        self.assertEqual(self.log["broken"]["discovery"]["capabilities"], ["tools"])

    def test_second_listing_is_served_from_cache_without_a_request(self):
        self.assertEqual([s["name"] for s in self.spans].count("MCP send tools/list"), 1)
        self.assertEqual([e["outcome"] for e in self.calls[:2]], ["result", "result"])

    def test_bad_arguments_and_unknown_tools_are_refused_before_sending(self):
        refused = [c for c in self.app["children"] if c["attributes"].get("app.outcome") == "refused_locally"]
        self.assertEqual(len(refused), 2)
        self.assertTrue(all(c["children"] == [] for c in refused))  # no request span: nothing was sent
        self.assertIn("42 is not of type 'string'", self.calls[3]["detail"])

    def test_tool_error_is_a_result_with_is_error(self):
        self.assertEqual((self.calls[4]["outcome"], self.calls[4]["detail"]), ("tool_error", "Error executing tool search_docs: The query is empty."))

    def test_timeout_is_local_and_the_server_still_finishes(self):
        self.assertEqual(self.calls[5]["outcome"], "timeout")
        client_span = next(c for c in self.app["children"] if c["name"] == "app call rebuild_index")["children"][0]
        self.assertEqual((client_span["kind"], client_span["status"]), ("CLIENT", "ERROR"))
        self.assertEqual((client_span["children"][0]["kind"], client_span["children"][0]["status"]), ("SERVER", "UNSET"))
        self.assertEqual(self.calls[6]["outcome"], "result")  # the next call is still answered
        self.assertIn("notifications/cancelled", [root["name"] for root in self.tree["roots"]])

    def test_server_spans_continue_the_client_trace(self):
        for span in self.spans:
            if span["kind"] == "CLIENT":
                self.assertEqual([child["kind"] for child in span["children"]], ["SERVER"])
        self.assertIn("docs.search", [s["name"] for s in self.spans])

    def test_output_that_breaks_the_schema_is_rejected(self):
        self.assertEqual(self.log["broken"]["log"][1]["outcome"], "invalid_output")
        self.assertEqual(self.log["broken"]["log"][1]["detail"], "'text' is a required property")

    def test_saved_fixtures_match_a_fresh_run(self):
        self.assertEqual(json.loads((HERE / "execution-log.json").read_text()), self.log)
        self.assertEqual(json.loads((HERE / "trace-tree.json").read_text()), self.tree)


class CapabilityGate(unittest.IsolatedAsyncioTestCase):
    async def test_tools_are_not_listed_when_the_server_does_not_offer_them(self):
        class NoTools:
            server_capabilities = SimpleNamespace(tools=None)

            async def list_tools(self):
                raise AssertionError("tools/list must not be sent")

        app = traced_client.TracedClient(NoTools())
        await app.load_tools()
        self.assertEqual(app.log, [{"request": "tools/list", "outcome": "skipped", "detail": "server does not offer tools"}])


if __name__ == "__main__":
    unittest.main()
