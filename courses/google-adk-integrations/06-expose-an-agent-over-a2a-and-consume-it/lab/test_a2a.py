"""Replay the recorded Gemini turns on both sides of a real A2A connection, offline.

Run: python -m unittest -v test_a2a.py
The server (to_a2a + uvicorn), the agent card, the JSON-RPC stream and RemoteA2aAgent are real;
both models are replaced by their recorded turns.
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

import httpx  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

import client  # noqa: E402
import record  # noqa: E402
import server  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
ROLLBACK = RECORD["runs"]["rollback"]


def setUpModule():
    warnings.simplefilter("ignore")  # unittest resets warning filters before the tests run


class ReplayLlm(BaseLlm):
    turns: list
    delay: float = 0

    async def generate_content_async(self, llm_request, stream=False):
        await asyncio.sleep(self.delay)
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def docs_server(delay: float = 0, card_port: int | None = None):
    port = server.free_port()
    remote = server.build_agent(ReplayLlm(model="replay", turns=list(ROLLBACK["remote_model_turns"]), delay=delay))
    return server.running(server.build_app(remote, port, card_port), port)


def ask(url: str, http_timeout: float = 60, **remote) -> tuple[str, list]:
    async def go():
        http, exchange = record.wire(http_timeout)
        coordinator = client.build_agent(ReplayLlm(model="replay", turns=list(ROLLBACK["model_turns"])),
                                         client.remote_docs(url, httpx_client=http, **remote))
        try:
            return client.show(await client.ask(ROLLBACK["question"], coordinator)), exchange
        finally:
            await http.aclose()
    return asyncio.run(go())


def states(exchange: list) -> list[str]:
    return [next(iter(e["result"].values())).get("status", {}).get("state", "artifact") for e in exchange[1]["response"]]


class A2ATests(unittest.TestCase):
    def test_a_server_thread_that_exits_does_not_hang_startup(self):
        class FailedServer:
            started = False
            should_exit = False
            def run(self):
                pass
        with patch.object(server.uvicorn, "Server", return_value=FailedServer()):
            with self.assertRaisesRegex(RuntimeError, "failed to start"):
                with server.running(object(), server.free_port(), startup_timeout=0.5):
                    self.fail("server never started")

    def test_the_card_describes_the_agent_and_its_tool(self):
        with docs_server() as url:
            card = httpx.get(f"{url}/.well-known/agent-card.json").json()
        self.assertEqual(card["supportedInterfaces"][0]["url"], url)
        self.assertEqual({k: v for k, v in card.items() if k != "supportedInterfaces"},
                         {k: v for k, v in RECORD["agent_card"].items() if k != "supportedInterfaces"})

    def test_the_rollback_question_crosses_a2a(self):
        with docs_server() as url:
            transcript, exchange = ask(url)
        self.assertEqual(transcript, ROLLBACK["transcript"])
        self.assertEqual([(e["method"], e["path"]) for e in exchange], [("GET", "/.well-known/agent-card.json"), ("POST", "/")])
        self.assertEqual(exchange[1]["request"]["method"], "SendStreamingMessage")

    def test_the_server_streams_the_task_through_its_states(self):
        with docs_server() as url:
            _, exchange = ask(url)
        self.assertEqual(states(exchange), states(ROLLBACK["exchange"]))
        self.assertEqual(states(exchange)[0], "TASK_STATE_SUBMITTED")
        self.assertEqual(states(exchange)[-1], "TASK_STATE_COMPLETED")

    def test_a_card_whose_rpc_url_has_another_origin_is_refused(self):
        with docs_server(card_port=server.free_port()) as url:
            transcript, exchange = ask(url)
        self.assertIn("Agent card RPC URL must have the same origin as the location the card was fetched from", transcript)
        self.assertEqual([e["method"] for e in exchange], ["GET"])

    def test_a_server_that_is_down_returns_an_error_event(self):
        transcript, _ = ask(f"http://localhost:{server.free_port()}")
        self.assertIn("docs_assistant: error None Failed to initialize remote A2A agent", transcript)
        self.assertIn("All connection attempts failed", transcript)

    def test_the_timeout_argument_is_ignored_with_your_own_http_client(self):
        with docs_server(delay=1.0) as url:
            ignored, _ = ask(url, timeout=0.3)
            timed_out, _ = ask(url, http_timeout=0.3)
        self.assertEqual(ignored, ROLLBACK["transcript"])
        self.assertEqual(timed_out.splitlines()[-1], "docs_assistant: error None A2A request failed: Client Request timed out")
        self.assertEqual(timed_out, RECORD["failures"]["timeout"]["transcript"])


class DocsPathSafety(unittest.TestCase):
    def test_read_page_refuses_an_out_of_tree_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "outside.txt").write_text("private content")
            (root / "docs/config.md").symlink_to(root / "outside.txt")
            with patch.object(server, "HERE", root), patch.object(server, "PAGES", ["config"]):
                result = server.read_page("config")
            self.assertIn("error", result)
            self.assertNotIn("private content", str(result))


if __name__ == "__main__":
    unittest.main()
