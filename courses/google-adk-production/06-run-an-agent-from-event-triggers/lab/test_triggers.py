"""Deliver the recorded events to main.py's app offline, with the model replaced by its recording.

Run: python -m unittest -v test_triggers.py
The trigger routes, their auth check, base64 decoding, retry loop and the post_review tool are real.
"""
import json
import logging
import os
import tempfile
import unittest
import warnings
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
os.environ["ADK_DISABLE_LOAD_DOTENV"] = "1"  # keep ancestor .env files out of offline tests
os.environ.update(DOCS_MODEL="replay-model", TRIGGER_TOKEN="test-token", ADK_TRIGGER_RETRY_BASE_DELAY="0.01",
                  DOCS_REVIEWS=str(Path(tempfile.mkdtemp()) / "reviews.jsonl"))

from fastapi.testclient import TestClient  # noqa: E402
from google.adk.cli.fast_api import get_fast_api_app  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.models.registry import LLMRegistry  # noqa: E402
from google.genai import types  # noqa: E402

import main  # noqa: E402
import publish  # noqa: E402
from docs_reviewer import agent as reviewer  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
REVIEWS = Path(os.environ["DOCS_REVIEWS"])


class ReplayLlm(BaseLlm):
    """Yields recorded responses in order; FAIL_FIRST raises that many errors first."""
    queue: list = []
    fail_first: list = []

    @classmethod
    def supported_models(cls):
        return [r"replay-.*"]

    async def generate_content_async(self, llm_request, stream=False):
        if ReplayLlm.fail_first:
            raise ReplayLlm.fail_first.pop(0)
        yield LlmResponse(content=types.Content.model_validate(ReplayLlm.queue.pop(0)["content"]))


LLMRegistry.register(ReplayLlm)
# Pin the loaded agent too: unittest discovery can import it before DOCS_MODEL is set.
reviewer.root_agent.model = ReplayLlm(model="replay-model")
# Discovery may also import the package before DOCS_REVIEWS is configured.
# Keep every tool write in the test sandbox, independent of import order.
reviewer.REVIEWS = REVIEWS


def turns(i: int) -> list:
    return list(RECORD["deliveries"][i]["session"]["model_turns"])


class Triggers(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")
        REVIEWS.unlink(missing_ok=True)
        ReplayLlm.fail_first = []
        self.http = TestClient(main.app)

    def deliver(self, source, page, event_id, raw=None, token="test-token"):
        return publish.deliver(self.http, source, page, event_id, raw, token)

    def test_concurrent_deliveries_append_one_review(self):
        REVIEWS.write_text("", encoding="utf-8")
        context = SimpleNamespace(state={"trigger_delivery": {"source": "pubsub", "id": "1001"}})
        original = Path.read_text
        def slow_read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == REVIEWS:
                time.sleep(0.05)  # widen the lookup/append race without changing the result
            return value
        with mock.patch.object(Path, "read_text", slow_read), ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: reviewer.post_review("tokens", "Review", context), range(8)))
        self.assertEqual(sum(r["posted"] for r in results), 1)
        self.assertEqual(len(REVIEWS.read_text().splitlines()), 1)

    def test_a_missing_delivery_id_cannot_post(self):
        with self.assertRaisesRegex(ValueError, "trigger delivery ID"):
            reviewer.post_review("tokens", "Review", SimpleNamespace(state={"trigger_delivery": {"source": "pubsub"}}))
        self.assertFalse(REVIEWS.exists())

    def test_a_page_path_cannot_leave_the_named_docs(self):
        with mock.patch.object(Path, "is_file", return_value=True), mock.patch.object(Path, "read_text", return_value="private"):
            self.assertIn("error", reviewer.read_page("../secret"))

    def test_a_pubsub_delivery_runs_the_agent_in_a_new_session(self):
        ReplayLlm.queue = turns(0)
        r = self.deliver("pubsub", "tokens", "1001")
        self.assertEqual((r.status_code, r.json()), (200, RECORD["deliveries"][0]["body"]))
        self.assertEqual([json.loads(l)["key"] for l in REVIEWS.read_text().splitlines()], ["pubsub:1001"])
        self.assertEqual(RECORD["deliveries"][0]["session"]["state"]["trigger_delivery"]["id"], "1001")

    def test_a_redelivered_message_does_not_post_twice(self):
        ReplayLlm.queue = turns(0) + turns(1)
        self.deliver("pubsub", "tokens", "1001")
        r = self.deliver("pubsub", "tokens", "1001")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(REVIEWS.read_text().splitlines()), 1)

    def test_an_eventarc_binary_mode_event_is_accepted(self):
        ReplayLlm.queue = turns(2)
        r = self.deliver("eventarc", "rollback", "ev-77")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(json.loads(REVIEWS.read_text().splitlines()[0])["key"], "eventarc:ev-77")

    def test_malformed_base64_is_rejected_with_400(self):
        r = self.deliver("pubsub", "tokens", "1002", raw="not base64!")
        self.assertEqual((r.status_code, r.json()), (400, RECORD["deliveries"][3]["body"]))
        self.assertFalse(REVIEWS.exists())

    def test_a_wrong_token_is_rejected_with_401(self):
        r = self.deliver("pubsub", "tokens", "1004", token="wrong-token")
        self.assertEqual((r.status_code, r.json()), (401, RECORD["deliveries"][4]["body"]))

    def test_the_cli_refuses_triggers_without_auth(self):
        with self.assertRaisesRegex(ValueError, "trigger_sources requires trigger_oidc_audience"):
            get_fast_api_app(agents_dir=main.AGENTS_DIR, web=False, trigger_sources=["pubsub"])
        self.assertEqual(RECORD["no_auth"]["exit"], 1)

    def test_an_oidc_audience_rejects_a_request_without_a_token(self):
        app = get_fast_api_app(agents_dir=main.AGENTS_DIR, web=False, session_service_uri="memory://",
                               trigger_sources=["pubsub"], trigger_oidc_audience="https://docs-reviewer.example")
        r = TestClient(app).post("/apps/docs_reviewer/trigger/pubsub", json=publish.pubsub_body("tokens", "1003"))
        self.assertEqual((r.status_code, r.json()), (401, RECORD["oidc_missing_token"]["body"]))

    def test_a_429_is_retried_and_then_succeeds(self):
        ReplayLlm.queue = turns(0)
        ReplayLlm.fail_first = [RuntimeError("429 RESOURCE_EXHAUSTED (injected)")]
        r = self.deliver("pubsub", "tokens", "1001")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(REVIEWS.read_text().splitlines()), 1)

    def test_a_non_transient_error_returns_500(self):
        ReplayLlm.fail_first = [RuntimeError("model unavailable (injected)")]
        r = self.deliver("pubsub", "tokens", "1005")
        self.assertEqual(r.status_code, 500)
        self.assertIn("Agent processing failed", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
