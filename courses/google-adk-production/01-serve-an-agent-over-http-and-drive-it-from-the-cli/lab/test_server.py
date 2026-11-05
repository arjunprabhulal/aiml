"""Replay the recorded model output through the real ADK API server app, offline.

Run: python -m unittest -v test_server.py
get_fast_api_app builds the same FastAPI app that `adk api_server` serves; only the model is replaced.
"""
import json
import logging
import os
import unittest
import warnings
from pathlib import Path
from unittest import mock

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
os.environ["ADK_DISABLE_LOAD_DOTENV"] = "1"  # keep ancestor .env files out of offline tests
os.environ["DOCS_MODEL"] = "replay-model"  # agent.py passes this string to ADK's model registry

from fastapi.testclient import TestClient  # noqa: E402
from google.adk.cli.fast_api import get_fast_api_app  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.models.registry import LLMRegistry  # noqa: E402
from google.genai import types  # noqa: E402

import client as c  # noqa: E402

HERE = Path(__file__).resolve().parent
RECORD = json.loads((HERE / "recorded-runs.json").read_text(encoding="utf-8"))


class ReplayLlm(BaseLlm):
    """Yields the recorded responses of one model call per request, partial chunks included."""
    queue: list = []

    @classmethod
    def supported_models(cls):
        return [r"replay-.*"]

    async def generate_content_async(self, llm_request, stream=False):
        while ReplayLlm.queue:
            turn = ReplayLlm.queue.pop(0)
            yield LlmResponse(content=types.Content.model_validate(turn["content"]), partial=turn["partial"] or None)
            if not turn["partial"]:
                return


LLMRegistry.register(ReplayLlm)
# unittest discovery may import agent packages before this test module sets DOCS_MODEL.
from docs_assistant import agent as loaded_agent
loaded_agent.root_agent.model = ReplayLlm(model="replay-model")


def server(**kwargs) -> TestClient:
    app = get_fast_api_app(agents_dir=str(HERE), web=False, session_service_uri="memory://",
                           artifact_service_uri="memory://", allow_origins=["http://localhost:3000"], **kwargs)
    return TestClient(app)


class ApiServer(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")  # unittest re-enables warnings per test
        self.http = server()

    def test_answer_skips_contentless_end_or_error_events(self):
        events = [{"author": "docs_assistant", "content": {"parts": [{"text": "Answer"}]}},
                  {"author": "docs_assistant", "content": None}]
        self.assertEqual(c.answer(events), "Answer")

    def test_run_returns_the_whole_turn_as_one_list(self):
        ReplayLlm.queue = list(RECORD["run"]["model_turns"])
        self.assertEqual(self.http.get("/list-apps").json(), RECORD["apps"])
        c.create_session(self.http, "s-run", {"team": "payments"})
        events = c.run(self.http, "s-run", RECORD["question"])
        self.assertEqual([c.describe(e) for e in events], RECORD["run"]["lines"])
        self.assertEqual(c.answer(events), RECORD["run"]["answer"])
        stored = self.http.get(f"/apps/{c.APP}/users/{c.USER}/sessions/s-run").json()
        self.assertEqual(stored["state"], {"team": "payments"})

    def test_run_sse_streams_partials_the_session_does_not_store(self):
        ReplayLlm.queue = list(RECORD["sse"]["model_turns"])
        c.create_session(self.http, "s-sse")
        events = list(c.run_sse(self.http, "s-sse", RECORD["question"]))
        self.assertEqual([c.describe(e) for e in events], RECORD["sse"]["lines"])
        stored = self.http.get(f"/apps/{c.APP}/users/{c.USER}/sessions/s-sse").json()
        self.assertEqual(len(stored["events"]), RECORD["sse"]["stored"])
        self.assertFalse(any(e.get("partial") for e in stored["events"]))

    def test_an_unknown_session_returns_404(self):
        body = {"app_name": c.APP, "user_id": c.USER, "session_id": "no-such-session", "new_message": c.message("hi")}
        r = self.http.post("/run", json=body)
        self.assertEqual((r.status_code, r.json()), (404, RECORD["failures"]["unknown_session"]["body"]))

    def test_auto_create_session_accepts_a_new_id(self):
        ReplayLlm.queue = list(RECORD["run"]["model_turns"])
        http = server(auto_create_session=True)
        events = c.run(http, "brand-new", RECORD["question"])
        self.assertEqual(c.answer(events), RECORD["run"]["answer"])

    def test_a_browser_origin_not_in_allow_origins_gets_403(self):
        body = {"app_name": c.APP, "user_id": c.USER, "session_id": "s-run", "new_message": c.message("hi")}
        r = self.http.post("/run", json=body, headers={"Origin": "https://docs-portal.example"})
        self.assertEqual((r.status_code, r.text), (403, RECORD["failures"]["origin"]["body"]))
        r = self.http.options("/run", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
        self.assertEqual(r.headers.get("access-control-allow-origin"), "http://localhost:3000")

    def test_the_deprecated_per_id_path_nests_the_state(self):
        r = self.http.post(f"/apps/{c.APP}/users/{c.USER}/sessions/s-old", json={"state": {"team": "payments"}})
        self.assertEqual(r.json()["state"], RECORD["failures"]["deprecated_path"]["state"])
        self.assertEqual(c.create_session(self.http, "s-new", {"team": "payments"})["state"], {"team": "payments"})


if __name__ == "__main__":
    unittest.main()
