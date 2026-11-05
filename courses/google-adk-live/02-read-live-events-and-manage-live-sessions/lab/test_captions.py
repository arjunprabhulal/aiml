"""Replay the recorded live session through ADK; inject a dropped connection; no network."""
import asyncio
import copy
import json
import logging
import unittest
from pathlib import Path

from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from websockets.exceptions import ConnectionClosedError

import live_harness
from captions import RUN_CONFIG, Captions, build_agent, make_runner, open_session
from live_harness import ReplayLive, read_pcm, say_audio, say_text, spoken, summarize
from record import barge_in, one_turn

HERE = Path(__file__).parent
RECORD = json.loads((HERE / "events-run.json").read_text())
live_harness.PACE = 0
logging.disable(logging.CRITICAL)  # ADK logs the injected failures; the assertions check them


def replay(*indexes, drop_after_handle=False, strip_handles=False):
    connections = [copy.deepcopy(RECORD["connections"][i]) for i in indexes]
    traffic = connections[0]["traffic"]
    if strip_handles:
        traffic[:] = [e for e in traffic if "live_session_resumption_update" not in e.get("received", {})]
    if drop_after_handle or strip_handles:
        mark = "live_session_resumption_update" if drop_after_handle else "output_transcription"
        at = next(i for i, e in enumerate(traffic) if e.get("received", {}).get(mark, {}).get(
            "new_handle" if drop_after_handle else "text"))
        traffic.insert(at + 1, {"raise": ConnectionClosedError(None, None)})
    return ReplayLive(model="replay", connections=connections, opened=[])


class LiveEvents(unittest.TestCase):
    def test_captions_keep_each_finished_line_once(self):
        captions = Captions()
        for row in RECORD["first"]:
            captions.apply(row)
        self.assertEqual([list(line) for line in captions.lines], RECORD["captions"])
        self.assertEqual(captions.state, "listening")

    def test_joining_every_fragment_doubles_the_transcript(self):
        naive = "".join(r["output_transcription"]["text"] for r in RECORD["first"] if "output_transcription" in r)
        first_line = RECORD["captions"][0][1]
        self.assertEqual(naive.count(first_line), 2)
        self.assertEqual(spoken(RECORD["first"]).count(first_line), 1)

    def test_barge_in_sets_interrupted_before_the_turn_completes(self):
        flags = [("interrupted" if r.get("interrupted") else "turn_complete")
                 for r in RECORD["first"] if r.get("interrupted") or r.get("turn_complete")]
        self.assertEqual(flags[:2], ["interrupted", "turn_complete"])

    def test_audio_is_streamed_but_not_saved(self):
        self.assertGreater(sum(r.get("audio_bytes", 0) for r in RECORD["first"]), 0)
        self.assertFalse(any("inline_data" in r["kinds"] for r in RECORD["saved_after_first"]))

    def test_a_new_connection_replays_the_saved_history(self):
        model = replay(0, 1)
        runner = make_runner(build_agent(model))

        async def run():
            session = await open_session(runner, "review-call")
            await barge_in(runner, session.id, LiveRequestQueue())
            await one_turn(runner, session.id, LiveRequestQueue(), say_audio(read_pcm(HERE / "followup.wav")))
        asyncio.run(run())
        self.assertEqual(model.opened[1][1].received[0], ("history", 4))

    def test_replayed_history_is_not_recall(self):
        self.assertNotIn("sample rate", spoken(RECORD["second"]))
        self.assertIn("sample rate", spoken(RECORD["third"]))

    def test_a_closed_queue_ends_run_live_with_no_events(self):
        runner = make_runner(build_agent(replay(0)))

        async def run():
            session = await open_session(runner, "review-call")
            queue = LiveRequestQueue()
            queue.close()
            return [summarize(e) async for e in runner.run_live(
                user_id="dev", session_id=session.id, live_request_queue=queue, run_config=RUN_CONFIG)]
        self.assertEqual(asyncio.run(run()), [])

    def test_a_drop_with_a_cached_handle_reconnects_without_history(self):
        model = replay(0, 1, drop_after_handle=True)
        runner = make_runner(build_agent(model))

        async def run():
            session = await open_session(runner, "review-call")
            await asyncio.wait_for(barge_in(runner, session.id, LiveRequestQueue()), 3)
        try:
            asyncio.run(run())
        except asyncio.TimeoutError:
            pass  # the second recording expects other input; reconnecting is what is under test
        request, connection = model.opened[1]
        self.assertTrue(request.live_connect_config.session_resumption.handle)
        self.assertNotIn("history", [kind for kind, _ in connection.received])

    def test_a_drop_without_a_handle_reaches_the_caller(self):
        runner = make_runner(build_agent(replay(0, strip_handles=True)))

        async def run():
            session = await open_session(runner, "review-call")
            await barge_in(runner, session.id, LiveRequestQueue())
        with self.assertRaises(ConnectionClosedError):
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
