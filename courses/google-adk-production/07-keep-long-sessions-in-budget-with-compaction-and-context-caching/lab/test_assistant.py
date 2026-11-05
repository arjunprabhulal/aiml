"""Replay the recorded Gemini turns offline and check what compaction does to the request.

Run: python -m unittest -v test_assistant.py
"""
import asyncio
import json
import logging
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.agents.context_cache_config import ContextCacheConfig  # noqa: E402
from google.adk.apps.app import App, EventsCompactionConfig  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

import assistant  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
BUDGETED, PLAIN = RECORD["runs"]


class ReplayLlm(BaseLlm):
    """Returns recorded responses in order and keeps every request it receives."""
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def replay(run: dict, compact: bool):
    """Run the six questions against recorded model turns; return the model requests and the stored session."""
    model = ReplayLlm(model="replay", turns=[c["turn"] for c in run["model_calls"]], requests=[])
    summaries = [{"role": "model", "parts": [{"text": c["summary"]}]} for c in run["compactions"]]
    summarizer = ReplayLlm(model="replay", turns=summaries, requests=[])
    app = assistant.make_app(assistant.root_agent.clone(update={"model": model}), cache=False,
                             compact=compact, summarizer_llm=summarizer)

    async def go():
        runner = assistant.make_runner(app)
        session = await runner.session_service.create_session(app_name="docs", user_id="dana")
        for question in [t["question"] for t in run["turns"]]:
            await assistant.ask(runner, session.id, question)
        stored = await runner.session_service.get_session(app_name="docs", user_id="dana", session_id=session.id)
        await runner.close()
        return model.requests, summarizer.requests, stored
    return asyncio.run(go())


class Compaction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.budgeted = replay(BUDGETED, compact=True)
        cls.plain = replay(PLAIN, compact=False)

    def test_compaction_runs_after_every_second_turn(self):
        _, summarizer_requests, stored = self.budgeted
        self.assertEqual(len(summarizer_requests), len(BUDGETED["compactions"]))
        self.assertEqual(sum(1 for e in stored.events if e.actions.compaction), len(BUDGETED["compactions"]))

    def test_compaction_shrinks_the_request_history(self):
        budgeted = [len(r.contents) for r in self.budgeted[0]]
        plain = [len(r.contents) for r in self.plain[0]]
        self.assertEqual(budgeted, [c["contents"] for c in BUDGETED["model_calls"]])
        self.assertEqual(plain, [c["contents"] for c in PLAIN["model_calls"]])
        self.assertLess(budgeted[-1], plain[-1])

    def test_raw_events_stay_in_the_session(self):
        stored_budgeted, stored_plain = self.budgeted[2], self.plain[2]
        raw = [e for e in stored_budgeted.events if not e.actions.compaction]
        self.assertEqual(len(raw), len(stored_plain.events))

    def test_the_summary_replaces_old_tool_results(self):
        def logs_in(request):
            return [p.function_response.response["release"] for c in request.contents for p in c.parts
                    if p.function_response and "release" in p.function_response.response]
        self.assertEqual(logs_in(self.budgeted[0][-1]), [])  # both raw deploy logs are gone from the request
        self.assertEqual(logs_in(self.plain[0][-1]), ["r42", "r43"])


class Configuration(unittest.TestCase):
    def test_a_half_sliding_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "compaction_interval and overlap_size must be set together"):
            EventsCompactionConfig(compaction_interval=2)

    def test_an_unknown_app_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "context_cache"):
            App(name="docs", root_agent=assistant.root_agent, context_cache=ContextCacheConfig())

    def test_the_manual_is_the_static_system_instruction(self):
        self.assertIn("<manual>", assistant.root_agent.static_instruction)
        self.assertIn("docuctl rollback", assistant.root_agent.static_instruction)


class RecordedCacheUse(unittest.TestCase):
    """Checks on the recorded Gemini run: these read recorded-runs.json and make no model call."""

    def test_the_first_call_after_each_compaction_misses_the_cache(self):
        compacted_after = [max(c["turns"]) for c in BUDGETED["compactions"]]
        for turn in BUDGETED["turns"]:
            if turn["turn"] - 1 in compacted_after:
                self.assertEqual(turn["usage"][0]["cache"], "fingerprint only")
                self.assertEqual(turn["usage"][0]["cached"], 0)

    def test_a_short_prefix_never_gets_a_cache(self):
        short = RECORD["failures"]["short_prefix"]
        self.assertTrue(all(u["cache"] == "fingerprint only" for u in short["usage"]))
        self.assertIn("too small for caching", short["cache_log"][0])


if __name__ == "__main__":
    unittest.main()
