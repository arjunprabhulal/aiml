"""Replay the recorded parallel function calls against each tool variant and a real slow server, offline.

Run: python -m unittest -v test_assistant.py
"""
import asyncio
import json
import logging
import os
import socket
import threading
import time
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
with socket.socket() as reservation:
    reservation.bind(("127.0.0.1", 0))
    TEST_PORT = reservation.getsockname()[1]
os.environ["DOCS_URL"] = f"http://127.0.0.1:{TEST_PORT}"

import uvicorn  # noqa: E402

import assistant  # noqa: E402
import docs_server  # noqa: E402
from record import QUESTION, ReplayLlm, overlap, renamed  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
TURNS = RECORD["live"]["model_turns"]
CALLS = RECORD["live"]["calls_per_model_turn"][0]
DELAY = docs_server.DELAY_SECONDS = 0.3  # a shorter delay keeps the test fast; the ratios are the same


def run(tool, run_config=None):
    docs_server.SERVED.clear()
    agent = assistant.make_agent(tool).clone(update={"model": ReplayLlm(model="replay", turns=renamed(TURNS, tool.__name__))})
    events = asyncio.run(assistant.ask(agent, QUESTION, run_config))
    return events, overlap(docs_server.SERVED)


class ParallelTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = uvicorn.Server(uvicorn.Config(docs_server.app, host="127.0.0.1", port=TEST_PORT, log_level="warning"))
        threading.Thread(target=cls.server.run, daemon=True).start()
        deadline = time.monotonic() + 5
        while not cls.server.started:
            if time.monotonic() >= deadline:
                raise RuntimeError("Test HTTP server did not start within five seconds")
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True

    def test_the_model_asked_for_every_page_in_one_response(self):
        self.assertEqual(CALLS, 5)
        self.assertEqual(RECORD["live"]["server"]["max_in_flight"], CALLS)

    def test_async_tool_calls_overlap(self):
        _, server = run(assistant.fetch_page)
        self.assertEqual(server["max_in_flight"], CALLS)
        self.assertLess(server["span_seconds"], 2 * DELAY)

    def test_sync_tool_calls_run_one_at_a_time(self):
        _, server = run(assistant.fetch_page_blocking)
        self.assertEqual(server["max_in_flight"], 1)
        self.assertGreaterEqual(server["span_seconds"], CALLS * DELAY * 0.95)

    def test_the_thread_pool_runs_at_most_max_workers_sync_calls(self):
        _, server = run(assistant.fetch_page_blocking, assistant.THREAD_POOL)
        workers = assistant.THREAD_POOL.tool_thread_pool_config.max_workers
        self.assertEqual(server["max_in_flight"], min(workers, CALLS))
        self.assertGreaterEqual(server["span_seconds"], 2 * DELAY * 0.95)  # five calls on four workers: two rounds

    def test_an_async_def_that_blocks_gets_no_help_from_the_pool(self):
        _, server = run(assistant.fetch_page_async_but_blocking, assistant.THREAD_POOL)
        self.assertEqual(server["max_in_flight"], 1)

    def test_a_missing_page_is_a_result_not_an_exception(self):
        events, _ = run(assistant.fetch_page)
        results = [r.response for e in events for r in e.get_function_responses()]
        self.assertIn({"page": "canary", "ok": False, "status": 404}, results)
        self.assertEqual(len(results), CALLS)


if __name__ == "__main__":
    unittest.main()
