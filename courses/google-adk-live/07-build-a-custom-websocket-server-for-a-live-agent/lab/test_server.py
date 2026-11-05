"""Drive the bridge with Starlette's test client and replayed Live traffic; no network, no API key."""
import asyncio
import copy
import json
import logging
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from google.adk.sessions import InMemorySessionService

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from live_harness import ReplayLive, read_pcm
from server import build_agent, create_app

HERE = Path(__file__).parent
RECORD = json.loads((HERE / "server-run.json").read_text())
PCM = read_pcm(HERE / "question.wav") + bytes(32000)
logging.disable(logging.CRITICAL)


def app_for(connections, max_sessions=2):
    model = ReplayLive(model="replay", connections=copy.deepcopy(connections), opened=[])
    return create_app(build_agent(model), max_sessions=max_sessions)


def ask(ws):
    for start in range(0, len(PCM), 3200):
        ws.send_bytes(PCM[start:start + 3200])
    frames = []
    while True:
        message = ws.receive()
        frames.append(message)
        if message.get("text") and json.loads(message["text"]).get("turnComplete"):
            return frames


class FakeSocket:
    def __init__(self):
        self.closed = []

    async def accept(self):
        pass

    async def receive(self):
        await asyncio.Event().wait()

    async def close(self, code=1000, reason=""):
        self.closed.append(code)


async def idle_live(**kwargs):
    await asyncio.Event().wait()
    yield  # an async generator that stays open until canceled


def endpoint(app):
    return next(r.endpoint for r in app.routes if getattr(r, "path", "").startswith("/ws/"))


class Bridge(unittest.TestCase):
    def test_duplicate_active_session_is_refused_without_replacing_the_first(self):
        async def check():
            runner = SimpleNamespace(session_service=InMemorySessionService(), run_live=idle_live)
            with patch("server.Runner", return_value=runner):
                app = create_app(build_agent(), max_sessions=2)
            first, second = FakeSocket(), FakeSocket()
            task = asyncio.create_task(endpoint(app)(first, "dev", "same"))
            await asyncio.sleep(0.02)
            try:
                await asyncio.wait_for(endpoint(app)(second, "dev", "same"), 0.1)
                self.assertEqual(second.closed, [1008])
                self.assertFalse(task.done())
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        asyncio.run(check())

    def test_session_setup_failure_releases_its_capacity_slot(self):
        async def check():
            async def broken(**kwargs):
                raise RuntimeError("session store unavailable")
            runner = SimpleNamespace(session_service=SimpleNamespace(get_session=broken), run_live=idle_live)
            with patch("server.Runner", return_value=runner):
                app = create_app(build_agent(), max_sessions=1)
            try:
                await endpoint(app)(FakeSocket(), "dev", "setup-error")
            except RuntimeError:
                pass
            self.assertEqual(app.state.active, set())
        asyncio.run(check())


    def test_audio_leaves_as_binary_frames_and_events_as_json(self):
        with TestClient(app_for(RECORD["answered"]["connections"])) as client:
            with client.websocket_connect("/ws/dev/call-1") as ws:
                frames = ask(ws)
        audio = [f["bytes"] for f in frames if f.get("bytes")]
        events = [json.loads(f["text"]) for f in frames if f.get("text")]
        self.assertGreater(sum(map(len, audio)), 0)
        self.assertFalse(any(p.get("inlineData") for e in events for p in e.get("content", {}).get("parts", [])))
        self.assertTrue(any("outputTranscription" in e for e in events))

    def test_base64_json_would_inflate_the_audio_by_a_third(self):
        answered = RECORD["answered"]
        self.assertAlmostEqual(answered["base64_bytes"] / answered["audio_bytes"], 4 / 3, places=2)

    def test_a_caller_over_the_cap_is_refused_with_1013(self):
        with TestClient(app_for(RECORD["answered"]["connections"], max_sessions=1)) as client:
            with client.websocket_connect("/ws/dev/call-a"):
                with client.websocket_connect("/ws/dev/call-b") as second:
                    with self.assertRaises(WebSocketDisconnect) as refused:
                        second.receive_bytes()
        self.assertEqual(refused.exception.code, 1013)
        self.assertEqual(RECORD["session_cap"]["second"]["closed"]["code"], 1013)

    def test_a_model_failure_closes_with_1011_and_the_reason(self):
        with TestClient(app_for([])) as client:
            with client.websocket_connect("/ws/dev/call-x") as ws:
                ws.send_bytes(PCM[:3200])
                with self.assertRaises(WebSocketDisconnect) as closed:
                    ws.receive_bytes()
        self.assertEqual((closed.exception.code, closed.exception.reason[:11]), (1011, "LookupError"))
        self.assertIn("bidiGenerateC", RECORD["model_error"]["closed"]["reason"])

    def test_an_idle_hang_up_ends_this_bridges_handler(self):
        app = app_for(RECORD["answered"]["connections"])
        with TestClient(app) as client:
            with client.websocket_connect("/ws/dev/call-1") as ws:
                ask(ws)
            deadline = time.monotonic() + 5
            while app.state.active and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(app.state.active, set())
        self.assertEqual(RECORD["hang_up"]["handlers_open_after_10_s"], [])

    def test_an_idle_hang_up_strands_the_gather_bridge(self):
        self.assertEqual(RECORD["gather_hang_up"]["handlers_open_after_10_s"], ["hang-up"])


if __name__ == "__main__":
    unittest.main()
