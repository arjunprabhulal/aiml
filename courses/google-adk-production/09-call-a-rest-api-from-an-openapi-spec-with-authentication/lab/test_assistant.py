"""Replay the recorded Gemini turns against the real local release API, offline.

Run: python -m unittest -v test_assistant.py
"""
import asyncio
import json
import logging
import os
import secrets
import socket
import threading
import time
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
os.environ["SHIP_API_KEY"] = secrets.token_urlsafe(24)

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from google.adk import Runner  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

import assistant  # noqa: E402
import ship_api  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
KEY = os.environ["SHIP_API_KEY"]


class ReplayLlm(BaseLlm):
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request.model_dump_json(exclude_none=True))
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def replay(tools, steps: list):
    model = ReplayLlm(model="replay", turns=[t for s in steps for t in s["model_turns"]], requests=[])
    runner = Runner(app_name="docs", agent=assistant.make_agent(tools).clone(update={"model": model}),
                    session_service=InMemorySessionService(), auto_create_session=True)

    async def go():
        events = []
        for step in steps:
            events.append(await assistant.ask(runner, "s1", step["question"]))
        await runner.close()
        return events
    return asyncio.run(go()), model


class ReleaseApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Bind a private ephemeral port so independent replay suites cannot collide.
        cls.listener = socket.socket()
        cls.listener.bind(("127.0.0.1", 0))
        cls.listener.listen()
        port = cls.listener.getsockname()[1]
        cls.server = uvicorn.Server(uvicorn.Config(ship_api.app, host="127.0.0.1", port=port, log_level="warning"))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [cls.listener]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 5
        while not cls.server.started:
            if not cls.thread.is_alive() or time.monotonic() >= deadline:
                cls.server.should_exit = True
                cls.listener.close()
                raise RuntimeError("local replay API failed to start within five seconds")
            time.sleep(0.05)
        cls.spec = assistant.load_spec(f"http://127.0.0.1:{port}")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls.listener.close()

    def setUp(self):
        ship_api.REQUESTS.clear()

    def tools(self, **kwargs):
        return asyncio.run(assistant.release_tools(self.spec, KEY, **kwargs).get_tools())

    def test_operations_become_snake_case_tools(self):
        self.assertEqual([t.name for t in self.tools()], ["list_releases", "get_release"])
        self.assertEqual([t.name for t in self.tools(tool_filter=None)],
                         ["list_releases", "get_release", "rollback_environment"])

    def test_operation_ids_in_the_filter_match_nothing(self):
        self.assertEqual(self.tools(tool_filter=["listReleases", "getRelease"]), [])
        self.assertEqual(RECORD["failures"]["camel_case_filter"], [])

    def test_the_key_is_a_header_and_absent_from_recorded_model_requests(self):
        events, model = replay(assistant.release_tools(self.spec, KEY), RECORD["run"]["steps"])
        self.assertEqual([h["key_sent"] for h in ship_api.REQUESTS], [True, True])
        self.assertTrue(all(KEY not in r for r in model.requests))
        result = events[0][-2].get_function_responses()[0].response
        self.assertEqual(result, RECORD["run"]["steps"][0]["results"][0])

    def test_each_call_carries_the_invocation_id(self):
        events, _ = replay(assistant.release_tools(self.spec, KEY), RECORD["run"]["steps"][:1])
        self.assertEqual(ship_api.REQUESTS[0]["request_id"], events[0][0].invocation_id)

    def test_a_wrong_key_comes_back_to_the_model_as_a_tool_error(self):
        steps = RECORD["failures"]["wrong_key"]["steps"]
        events, _ = replay(assistant.release_tools(self.spec, "not-the-key"), steps)
        error = [r.response for e in events[0] for r in e.get_function_responses()][0]["error"]
        self.assertIn("Status Code: 401", error)

    def test_a_spec_without_servers_fails_the_run(self):
        spec = {k: v for k, v in self.spec.items() if k != "servers"}
        with self.assertRaisesRegex(httpx.UnsupportedProtocol, "missing an 'http://' or 'https://'"):
            replay(assistant.release_tools(spec, KEY), RECORD["failures"]["no_servers"]["steps"])
        self.assertEqual(ship_api.REQUESTS, [])

    def test_the_model_was_never_offered_the_rollback_operation(self):
        names = [d["name"] for d in RECORD["run"]["declarations"]]
        self.assertEqual(names, ["list_releases", "get_release"])
        self.assertEqual(RECORD["run"]["steps"][2]["calls"], [])


if __name__ == "__main__":
    unittest.main()
