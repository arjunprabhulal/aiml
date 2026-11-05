"""Replay the recorded Live traffic through ADK's run_live loop; no network, no API key."""
import asyncio
import json
import logging
import tempfile
import unittest
import wave
from pathlib import Path

from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.adk.errors.session_not_found_error import SessionNotFoundError
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

import live_harness
from live_harness import ReplayLive, read_pcm, say_audio, say_text
from voice_docs_helper import ask, build_agent, mentions

HERE = Path(__file__).parent
RECORD = json.loads((HERE / "stream-run.json").read_text())
RUNS = {run["name"]: run for run in RECORD["runs"]}
FAILURES = {f["name"]: f["error"] for f in RECORD["failures"]}
live_harness.PACE = 0
logging.disable(logging.CRITICAL)  # ADK logs the injected failures; the assertions check them  # stream recorded clips without waiting in real time


def replay(name):
    return ReplayLive(model="replay", connections=json.loads(json.dumps(RUNS[name]["connections"])), opened=[])


class VoiceDocsHelper(unittest.TestCase):
    def test_text_turn_replays_audio_and_a_transcript(self):
        model = replay("text turn")
        rows, answer = asyncio.run(ask(build_agent(model), say_text(RECORD["question"])))
        self.assertEqual(answer, RUNS["text turn"]["answer"])
        self.assertGreater(sum(r.get("audio_bytes", 0) for r in rows), 0)
        self.assertTrue(rows[-1].get("turn_complete"))

    def test_spoken_turn_streams_16khz_pcm_chunks(self):
        model = replay("spoken turn")
        asyncio.run(ask(build_agent(model), say_audio(read_pcm(HERE / "question.wav"))))
        sent = [item for _, connection in model.opened for item in connection.received]
        self.assertEqual({mime for kind, mime in sent if kind == "realtime"}, {"audio/pcm;rate=16000"})

    def test_a_44khz_clip_is_refused_before_it_is_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cd-quality.wav"
            with wave.open(str(path), "wb") as clip:
                clip.setnchannels(1), clip.setsampwidth(2), clip.setframerate(44100)
                clip.writeframes(bytes(4410))
            with self.assertRaisesRegex(ValueError, "not \\(16000 Hz"):
                read_pcm(path)

    def test_ungrounded_answers_fail_the_check(self):
        trials = [run for name, run in RUNS.items() if name.startswith("ungrounded")]
        self.assertTrue(trials)
        for run in trials:
            self.assertFalse(mentions(run["answer"], "Agent Development Kit"), run["answer"])

    def test_text_response_modality_is_rejected(self):
        self.assertIn("response modalities (TEXT) is not supported", FAILURES["TEXT response modality"])

    def test_a_standard_model_is_not_served_over_bidi(self):
        self.assertIn("not supported for bidiGenerateContent", FAILURES["standard Gemini model"])

    def test_run_live_needs_an_existing_session(self):
        runner = Runner(app_name="voice_docs", agent=build_agent(replay("text turn")),
                        session_service=InMemorySessionService())

        async def run():
            async for _ in runner.run_live(user_id="dev", session_id="never-created",
                                           live_request_queue=LiveRequestQueue(), run_config=RunConfig()):
                pass
        with self.assertRaises(SessionNotFoundError):
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
