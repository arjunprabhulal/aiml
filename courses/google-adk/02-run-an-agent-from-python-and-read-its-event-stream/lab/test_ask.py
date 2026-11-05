"""Replay the recorded model output through ask.py's runner, offline.

Run: python -m unittest -v test_ask.py
The model is replaced by its recorded responses; the Runner, session service and tool are real.
"""
import asyncio
import json
import logging
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)  # ADK logs each expected failure with a traceback

from google.adk import Runner  # noqa: E402
from google.adk.agents import RunConfig  # noqa: E402
from google.adk.agents.invocation_context import LlmCallsLimitExceededError  # noqa: E402
from google.adk.agents.run_config import StreamingMode  # noqa: E402
from google.adk.errors.session_not_found_error import SessionNotFoundError  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

import ask  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-events.json").read_text(encoding="utf-8"))


class ReplayLlm(BaseLlm):
    """Yields the recorded responses of one model call per request, partial chunks included."""
    turns: list

    async def generate_content_async(self, llm_request, stream=False):
        while self.turns:
            turn = self.turns.pop(0)
            yield LlmResponse(content=types.Content.model_validate(turn["content"]), partial=turn["partial"] or None)
            if not turn["partial"]:
                return


def replay(mode: str, max_llm_calls: int = 10, session_id: str | None = None):
    agent = ask.root_agent.clone(update={"model": ReplayLlm(model="replay", turns=list(RECORD[mode.lower()]["model_turns"]))})
    sessions = InMemorySessionService()
    runner = Runner(app_name=ask.APP, agent=agent, session_service=sessions)

    async def go():
        sid = session_id or (await sessions.create_session(app_name=ask.APP, user_id=ask.USER)).id
        config = RunConfig(streaming_mode=StreamingMode[mode], max_llm_calls=max_llm_calls)
        try:
            events = await ask.ask(runner, sid, RECORD["question"], config)
        finally:
            await runner.close()
        stored = await sessions.get_session(app_name=ask.APP, user_id=ask.USER, session_id=sid)
        return events, stored

    return asyncio.run(go())


class EventStream(unittest.TestCase):
    def test_a_tool_call_yields_four_events_in_order(self):
        events, stored = replay("NONE")
        self.assertEqual([ask.describe(e) for e in events], RECORD["none"]["lines"])
        self.assertEqual(len(stored.events), RECORD["none"]["stored"])

    def test_streaming_yields_partial_chunks_that_the_session_does_not_store(self):
        events, stored = replay("SSE")
        self.assertEqual([ask.describe(e) for e in events], RECORD["sse"]["lines"])
        self.assertGreater(sum(1 for e in events if e.partial), 0)
        self.assertFalse(any(e.partial for e in stored.events))
        self.assertEqual(len(stored.events), RECORD["sse"]["stored"])

    def test_the_answer_is_the_agents_last_final_event(self):
        events, _ = replay("SSE")
        self.assertEqual(ask.answer(events), RECORD["sse"]["answer"])
        self.assertTrue(events[0].is_final_response())  # the user's own message
        self.assertEqual(ask.answer(events[:1]), "")

    def test_an_unknown_session_id_raises(self):
        with self.assertRaises(SessionNotFoundError):
            replay("NONE", session_id="no-such-session")

    def test_max_llm_calls_stops_the_invocation(self):
        with self.assertRaises(LlmCallsLimitExceededError):
            replay("NONE", max_llm_calls=1)


if __name__ == "__main__":
    unittest.main()
