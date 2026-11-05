"""Send audio and JPEG frames to a live agent, choose its voice, and take turns without server VAD."""
import asyncio

from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.models import Gemini
from google.genai import types

from live_harness import MODEL, PACE, RATE_IN

INSTRUCTION = ("You are the docs assistant on a call. The caller may share their screen as images. "
               "Answer in one short spoken sentence, and quote names exactly as they appear on screen.")


def voice(name: str, language: str = "en-US") -> types.SpeechConfig:
    return types.SpeechConfig(language_code=language, voice_config=types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=name)))


def build_agent(model=MODEL, agent_voice: str | None = None) -> Agent:
    """A voice set on the Gemini model object wins over RunConfig.speech_config."""
    if agent_voice:
        model = Gemini(model=model) if isinstance(model, str) else model
        model.speech_config = voice(agent_voice)
    return Agent(name="docs_helper", model=model, instruction=INSTRUCTION)


def session_config(voice_name="Kore", push_to_talk=False) -> RunConfig:
    vad = types.RealtimeInputConfig(automatic_activity_detection=types.AutomaticActivityDetection(disabled=True))
    return RunConfig(response_modalities=["AUDIO"], speech_config=voice(voice_name),
                     realtime_input_config=vad if push_to_talk else None)


def share_screen(frames: list[bytes], fps: float = 1.0):
    """A video stream is a sequence of JPEG stills; about one per second is the recommended maximum."""
    async def send(queue):
        for frame in frames:
            queue.send_realtime(types.Blob(mime_type="image/jpeg", data=frame))
            await asyncio.sleep(PACE / fps)
    return send


def push_to_talk(pcm: bytes, rate: int = RATE_IN):
    """With server VAD off, the client marks the turn: activity start, the audio, activity end."""
    step = rate * 2 // 10

    async def send(queue):
        queue.send_activity_start()
        for start in range(0, len(pcm), step):
            queue.send_realtime(types.Blob(mime_type=f"audio/pcm;rate={rate}", data=pcm[start:start + step]))
            await asyncio.sleep(PACE * 0.1)
        queue.send_activity_end()
    return send


def then(*senders):
    """Run several senders in order as one turn, for example frames and then a question."""
    async def send(queue):
        for sender in senders:
            await sender(queue)
    return send
