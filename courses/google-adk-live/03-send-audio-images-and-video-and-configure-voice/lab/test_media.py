"""Replay the recorded media runs through ADK's run_live loop; no network, no API key."""
import asyncio
import copy
import json
import logging
import unittest
from pathlib import Path

from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import live_harness
from live_harness import ReplayLive, read_pcm, say_audio, say_text, spoken, talk
from media import build_agent, push_to_talk, session_config, share_screen, then

HERE = Path(__file__).parent
RECORD = json.loads((HERE / "media-run.json").read_text())
RUNS = {run["name"]: run for run in RECORD["runs"]}
FRAMES = [(HERE / f"frame-{n}.jpg").read_bytes() for n in (1, 2, 3)]
live_harness.PACE = 0
logging.disable(logging.CRITICAL)


def replay(name, model_id="replay"):
    connections = copy.deepcopy(RUNS[name]["connections"]) if name else [{"traffic": []}]
    return ReplayLive(model=model_id, connections=connections, opened=[])


def converse(model, turn, run_config, timeout=10):
    async def run():
        runner = Runner(app_name="voice_docs", agent=build_agent(model), session_service=InMemorySessionService())
        session = await runner.session_service.create_session(app_name="voice_docs", user_id="dev")
        return await talk(runner, session.id, run_config, [turn], timeout=timeout)
    return asyncio.run(run())


def sent_kinds(model):
    return [mime for _, connection in model.opened for kind, mime in connection.received if kind == "realtime"]


class LiveMedia(unittest.TestCase):
    def test_frames_go_before_the_question_as_jpeg_blobs(self):
        model = replay("screen frames, then a spoken question")
        rows = converse(model, then(share_screen(FRAMES), say_audio(read_pcm(HERE / "which-test.wav"))), session_config())
        self.assertEqual(spoken(rows), RUNS["screen frames, then a spoken question"]["answer"])
        kinds = sent_kinds(model)
        self.assertEqual(kinds[:3], ["image/jpeg"] * 3)
        self.assertEqual(set(kinds[3:]), {"audio/pcm;rate=16000"})

    def test_push_to_talk_brackets_the_audio_with_activity_signals(self):
        model = replay("push-to-talk turn")
        converse(model, push_to_talk(read_pcm(HERE / "question.wav")), session_config(push_to_talk=True))
        kinds = sent_kinds(model)
        self.assertEqual((kinds[0], kinds[-1]), ("ActivityStart", "ActivityEnd"))

    def test_the_agent_voice_wins_over_the_session_voice(self):
        config = RUNS["agent voice over session voice"]["connections"][0]["config"]
        self.assertEqual(config["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"], "Puck")

    def test_unconverted_8khz_audio_garbles_the_transcript(self):
        run = RUNS["8 kHz audio labelled 16 kHz"]
        self.assertNotEqual(run["heard"], RUNS["push-to-talk turn"]["heard"])
        self.assertFalse(run["check"]["passed"])

    def test_with_vad_off_and_no_signals_no_turn_completes(self):
        with self.assertRaises(asyncio.TimeoutError):
            converse(replay("VAD off, no activity signals"), say_audio(read_pcm(HERE / "question.wav")),
                     session_config(push_to_talk=True), timeout=2)
        self.assertIn("TimeoutError", RUNS["VAD off, no activity signals"]["error"])

    def test_an_unknown_voice_fails_at_connect(self):
        self.assertIn("'Narrator' is not available", RUNS["unknown voice name"]["error"])

    def test_adk_drops_proactivity_for_gemini_3_live_models(self):
        config = RunConfig(response_modalities=["AUDIO"], proactivity=types.ProactivityConfig(proactive_audio=True))
        for model_id, kept in (("gemini-3.1-flash-live-preview", False), ("gemini-2.5-flash-native-audio-preview-12-2025", True)):
            model = replay(None, model_id)
            with self.assertRaises(asyncio.TimeoutError):
                converse(model, say_text("Say hello."), config, timeout=1)
            self.assertEqual(model.opened[0][0].live_connect_config.proactivity is not None, kept, model_id)
        self.assertNotIn("proactivity", RUNS["proactivity on Gemini 3.1 Flash Live"]["connections"][0]["config"])

    def test_ungrounded_answers_fail_the_check(self):
        self.assertFalse(RUNS["push-to-talk turn"]["check"]["passed"])
        self.assertTrue(RUNS["screen frames, then a spoken question"]["check"]["passed"])


if __name__ == "__main__":
    unittest.main()
