"""Replay the recorded Gemini turns through the real agent and VertexAiSearchTool, offline.

Run: python -m unittest -v test_agent.py
The model is replaced by its recorded turns, including the grounding metadata Agent Search returned,
so nothing reaches Google Cloud. ADK still builds every request, so the tests see the retrieval config.
"""
import asyncio
import json
import logging
import os
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.agents.readonly_context import ReadonlyContext  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_request import LlmRequest  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.tools.discovery_engine_search_tool import DiscoveryEngineSearchTool  # noqa: E402
from google.genai import types  # noqa: E402

# Fixture project only: cloud clients and model calls are replaced in these tests.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "vertex-ai-experminent")
RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
# Replay the actual exercise store ID; no cloud store is contacted.
os.environ["DOCS_SEARCH_STORE"] = RECORD["runs"]["postmortem"]["retrieval"][0]["vertex_ai_search"]["datastore"].rsplit("/", 1)[-1]
import agent  # noqa: E402


def setUpModule():
    warnings.simplefilter("ignore")


class ReplayLlm(BaseLlm):
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        turn = self.turns.pop(0)
        yield LlmResponse(
            content=types.Content.model_validate(turn["content"]) if turn["content"] else None,
            grounding_metadata=types.GroundingMetadata.model_validate(turn["grounding_metadata"])
            if turn["grounding_metadata"] else None)


def replay(run: dict) -> tuple[list, ReplayLlm]:
    model = ReplayLlm(model=RECORD["model"], turns=list(run["model_turns"]), requests=[])
    events = asyncio.run(agent.ask("replayed question", agent.build_agent(model), team=run["team"]))
    return events, model


def retrieval(model: ReplayLlm) -> list[dict]:
    return [t.retrieval.model_dump(mode="json", exclude_none=True)
            for t in model.requests[0].config.tools if t.retrieval]


class AgentSearchTests(unittest.TestCase):
    def test_the_tool_is_a_retrieval_config_not_a_function(self):
        events, model = replay(RECORD["runs"]["postmortem"])
        self.assertEqual(retrieval(model), RECORD["runs"]["postmortem"]["retrieval"])
        self.assertFalse(any(t.function_declarations for t in model.requests[0].config.tools))
        self.assertEqual(agent.sources([e for e in events if e.grounding_metadata][-1]),
                         RECORD["runs"]["postmortem"]["sources"])

    def test_the_team_filter_comes_from_session_state(self):
        for key, team in (("team-docs", "docs"), ("team-platform", "platform")):
            _, model = replay(RECORD["runs"][key])
            self.assertEqual(retrieval(model)[0]["vertex_ai_search"]["filter"], f'team: ANY("{team}")')
        self.assertEqual(RECORD["runs"]["team-docs"]["sources"], [])
        self.assertEqual(RECORD["runs"]["team-platform"]["sources"], ["Runbook: rotate the release signing key"])

    def test_an_unindexed_store_returns_no_sources(self):
        run = RECORD["not_indexed"]
        self.assertEqual(run["sources"], [])
        self.assertIn("found no document", run["transcript"])

    def test_a_question_the_store_cannot_answer_gets_no_sources(self):
        run = RECORD["runs"]["not-found"]
        events, _ = replay(run)
        self.assertEqual(agent.show(events), run["transcript"])
        self.assertIn("no document", run["transcript"].lower())

    def test_a_non_gemini_model_is_refused(self):
        request = LlmRequest(model="ollama_chat/gemma4:e2b")
        tool = agent.TeamSearch(data_store_id=agent.STORE)
        with self.assertRaisesRegex(ValueError, "Vertex AI search tool is not supported for model"):
            asyncio.run(tool.process_llm_request(tool_context=None, llm_request=request))

    def test_bypass_multi_tools_limit_drops_the_team_filter(self):
        def list_pages() -> list[str]:
            """List the public docs pages."""
            return []

        # Demonstrate the installed base-class behavior; TeamSearch refuses this mode.
        search = agent.VertexAiSearchTool(data_store_id=agent.STORE, max_results=3, bypass_multi_tools_limit=True)
        mixed = agent.build_agent(search=search).clone(update={"tools": [search, list_pages]})
        tools = asyncio.run(mixed.canonical_tools(None))
        replaced = [t for t in tools if isinstance(t, DiscoveryEngineSearchTool)]
        self.assertEqual(len(replaced), 1)
        self.assertNotIsInstance(replaced[0], agent.TeamSearch)
        self.assertIsNone(replaced[0]._filter)  # the per-team filter from TeamSearch is gone


class TeamFilterSafetyTests(unittest.TestCase):
    def test_missing_unknown_and_filter_syntax_teams_are_refused(self):
        tool = agent.TeamSearch(data_store_id=agent.STORE)
        for team in (None, "", "unknown", 'docs") OR team: ANY("platform', ["docs"]):
            with self.subTest(team=team), self.assertRaisesRegex(ValueError, "known team"):
                tool._build_vertex_ai_search_config(SimpleNamespace(state={"team": team}))

    def test_team_search_refuses_a_mode_that_discards_its_dynamic_filter(self):
        with self.assertRaisesRegex(ValueError, "dynamic team filter"):
            agent.TeamSearch(data_store_id=agent.STORE, bypass_multi_tools_limit=True)


if __name__ == "__main__":
    unittest.main()
