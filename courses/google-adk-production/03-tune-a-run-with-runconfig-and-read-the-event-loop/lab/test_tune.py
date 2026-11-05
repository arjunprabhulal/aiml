"""Replay the recorded model output through tune.py's runner, offline.

Run: python -m unittest -v test_tune.py
The model is replaced by its recorded responses; the Runner, RunConfig handling, session service and tool are real.
"""
import asyncio
import json
import logging
import unittest
import warnings
from pathlib import Path
from unittest import mock

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk import Runner  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

import tune  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))


class ReplayLlm(BaseLlm):
    """Yields one recorded response per call and keeps each request; raises when the recording ends."""
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        if not self.turns:
            raise RuntimeError("no recorded response for this call")
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)["content"]))


def replay(name: str):
    rec = RECORD[name]
    model = ReplayLlm(model="replay", turns=list(rec["model_turns"]), requests=[])
    runner = Runner(app_name=tune.APP, agent=tune.root_agent.clone(update={"model": model}), session_service=InMemorySessionService())

    async def go():
        tune.LOG.clear()
        session = await runner.session_service.create_session(app_name=tune.APP, user_id=tune.USER)
        error = None
        try:
            for request_id, text, recent, timeout_ms in rec["turns"]:
                await tune.ask(runner, session.id, text, tune.run_config(request_id, recent, timeout_ms))
        except RuntimeError as exc:
            error = exc
        finally:
            await runner.close()
        stored = await runner.session_service.get_session(app_name=tune.APP, user_id=tune.USER, session_id=session.id)
        return model.requests, stored, error

    return asyncio.run(go())


def recorded(name: str, prefix: str) -> list:
    return [line for line in RECORD[name]["log"] if line.startswith(prefix)]


class RunConfigAndEventLoop(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")

    def test_a_page_path_is_rejected_before_state_or_file_access(self):
        with mock.patch.object(Path, "is_file", return_value=True), mock.patch.object(Path, "read_text", return_value="private"):
            self.assertIn("error", asyncio.run(tune.read_page("../secret", None)))

    def test_state_commits_when_the_runner_appends_the_event(self):
        replay("tuned")
        self.assertEqual([l for l in tune.LOG if l.startswith(("  tool", "  event"))], recorded("tuned", ("  tool", "  event")))
        tool_line = next(l for l in tune.LOG if l.startswith("  tool"))
        self.assertIn("state[last_page]='rollback' stored[last_page]=None", tool_line)

    def test_custom_metadata_is_stamped_on_every_stored_event(self):
        _, stored, _ = replay("tuned")
        tagged = {e.invocation_id: e.custom_metadata["request_id"] for e in stored.events if e.author != "user"}
        self.assertEqual(sorted(tagged.values()), ["req-1", "req-2", "req-3"])

    def test_num_recent_events_limits_the_history_the_model_receives(self):
        requests, _, _ = replay("tuned")
        self.assertEqual([f"  model  call with {len(r.contents)} contents" for r in requests], recorded("tuned", "  model"))
        self.assertEqual(requests[-1].contents[0].parts[0].text, "Which page covers CI tokens?")

    def test_recorded_capped_answer_does_not_recall_the_first_question(self):
        self.assertEqual(RECORD["tuned"]["turns"][0][1], "How do I roll back production?")
        answer = next(line for line in reversed(RECORD["tuned"]["log"]) if line.startswith("  answer:"))
        self.assertIn("Which page covers CI tokens?", answer)
        self.assertNotIn("How do I roll back production?", answer)

    def test_a_cap_of_3_starts_the_history_at_a_function_call(self):
        requests, _, error = replay("cap_at_function_call")
        self.assertIsNotNone(error)  # the recording has no response: Gemini rejected this request with 400
        first = requests[-1].contents[0]
        self.assertEqual(first.role, "model")
        self.assertIsNotNone(first.parts[0].function_call)
        self.assertIn("INVALID_ARGUMENT", RECORD["cap_at_function_call"]["error"])

    def test_the_http_timeout_reaches_the_model_request(self):
        requests, _, _ = replay("timeout")
        self.assertEqual(requests[0].config.http_options.timeout, 1)
        self.assertEqual(requests[0].config.http_options.retry_options.attempts, 3)
        self.assertTrue(RECORD["timeout"]["error"].startswith("httpx.ConnectTimeout"))


if __name__ == "__main__":
    unittest.main()
