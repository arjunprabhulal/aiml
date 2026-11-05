"""Replay the recorded Gemini responses, offline, through the real ADK agent loop.

Run: python -m unittest -v test_agent.py
Gemini ran Google Search and code execution server-side when recording; the replay feeds those
responses back, so read_page, ADK's request building and the grounding parsing are real.
"""
import asyncio
import json
import logging
from unittest.mock import patch
import unittest
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.lite_llm import LiteLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.tools.google_search_tool import GoogleSearchTool  # noqa: E402

import agent  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
TEXT = {"content": {"role": "model", "parts": [{"text": "ok"}]}}


def setUpModule():
    warnings.simplefilter("ignore")  # unittest resets warning filters before the tests run


class ReplayLlm(BaseLlm):
    responses: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        yield LlmResponse.model_validate(self.responses.pop(0))


def replay(responses: list, **build) -> tuple[list, ReplayLlm]:
    # Named like the recorded model: ADK refuses built-in tools for a model id that is not gemini-*.
    model = ReplayLlm(model=RECORD["model"], responses=list(responses), requests=[])
    return asyncio.run(agent.ask("replayed question", agent.build_agent(model, **build))), model


def request_tools(request) -> list[str]:
    return sorted(k for t in request.config.tools for k in t.model_dump(exclude_none=True))


class BuiltInToolsTests(unittest.TestCase):
    def test_the_pin_check_replays_with_its_grounding_sources(self):
        run = RECORD["runs"]["pin"]
        events, _ = replay(run["responses"])
        self.assertEqual(agent.show(events), run["transcript"])
        self.assertEqual(agent.sources(events), run["sources"])
        self.assertIn("server GOOGLE_SEARCH_WEB", agent.show(events))

    def test_built_in_and_function_tools_share_one_request(self):
        _, model = replay(RECORD["runs"]["pin"]["responses"])
        self.assertEqual(request_tools(model.requests[0]), ["code_execution", "function_declarations", "google_search"])
        self.assertTrue(model.requests[0].config.tool_config.include_server_side_tool_invocations)

    def test_code_execution_runs_on_gemini_and_returns_its_output(self):
        run = RECORD["runs"]["slo"]
        events, _ = replay(run["responses"])
        transcript = agent.show(events)
        self.assertEqual(transcript, run["transcript"])
        self.assertIn("output OUTCOME_OK", transcript)
        self.assertIn("p95 linear: 118.2", transcript)

    def test_without_the_flag_gemini_rejects_built_in_plus_function_tools(self):
        self.assertIn("include_server_side_tool_invocations", RECORD["failures"]["no_flag"])
        self.assertTrue(RECORD["failures"]["no_flag"].startswith("ClientError: 400 INVALID_ARGUMENT"))
        _, model = replay([TEXT], combine=False)
        self.assertIsNone(model.requests[0].config.tool_config)
        self.assertIn("google_search", request_tools(model.requests[0]))

    def test_a_non_gemini_model_is_refused_before_any_call(self):
        assistant = agent.build_agent(LiteLlm(model="ollama_chat/gemma4:e2b"), code=False)
        with self.assertRaises(ValueError) as caught:
            asyncio.run(agent.ask("replayed question", assistant))
        self.assertEqual(f"ValueError: {caught.exception}", RECORD["failures"]["gemma"])

    def test_grounding_sources_come_from_metadata_not_answer_text(self):
        run = RECORD["runs"]["pin"]
        events, _ = replay(run["responses"])
        self.assertEqual(agent.sources(events), run["sources"])
        self.assertEqual(agent.citations(events), run["citations"])
        self.assertTrue(all(c["sources"] for c in run["citations"]))
        for citation in run["citations"]:
            self.assertTrue(set(citation["sources"]).issubset(
                {source["title"] for source in run["sources"]}))

    def test_the_answer_names_a_source_that_grounding_does_not_list(self):
        # Controlled response, not a provider recording: the generated text
        # names PyPI while its metadata lists only an unrelated example page.
        text = "According to PyPI, the package is current."
        response = {
            "content": {"role": "model", "parts": [{"text": text}]},
            "grounding_metadata": {
                "grounding_chunks": [{"web": {
                    "title": "Example release page", "uri": "https://example.org/release"}}],
                "grounding_supports": [{"segment": {
                    "start_index": 0, "end_index": len(text), "text": text},
                    "grounding_chunk_indices": [0]}]}}
        events, _ = replay([response])
        self.assertIn("answer " + text, agent.show(events))
        self.assertEqual(agent.sources(events), [{
            "title": "Example release page", "uri": "https://example.org/release"}])
        self.assertEqual(agent.citations(events), [{
            "text": text, "sources": ["Example release page"]}])
        self.assertFalse(any("pypi" in source["uri"] for source in agent.sources(events)))
        # Neither the runtime nor this presentation helper rejects the claim:
        # source extraction is not an independent factual validation step.

    def test_bypass_wraps_search_in_a_sub_agent_tool(self):
        tools = [agent.read_page, GoogleSearchTool(bypass_multi_tools_limit=True)]
        _, model = replay([TEXT], combine=False, code=False, tools=tools)
        declared = sorted(d.name for t in model.requests[0].config.tools for d in t.function_declarations or [])
        self.assertEqual(declared, ["google_search_agent", "read_page"])
        self.assertEqual(request_tools(model.requests[0]), ["function_declarations"])


class DocsPathSafety(unittest.TestCase):
    def test_read_page_refuses_an_out_of_tree_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "outside.txt").write_text("private content")
            (root / "docs/config.md").symlink_to(root / "outside.txt")
            with patch.object(agent, "HERE", root), patch.object(agent, "PAGES", ["config"]):
                result = agent.read_page("config")
            self.assertIn("error", result)
            self.assertNotIn("private content", str(result))


if __name__ == "__main__":
    unittest.main()
