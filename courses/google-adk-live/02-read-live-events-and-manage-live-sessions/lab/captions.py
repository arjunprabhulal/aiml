"""Fold a live event stream into captions and UI state, and keep one ADK session across connections."""
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from live_harness import MODEL

DOCS = (Path(__file__).parent / "docs/live-streaming.md").read_text()
APP = "voice_docs"

RUN_CONFIG = RunConfig(
    response_modalities=["AUDIO"],
    # ADK caches each resumption handle and reconnects with it when the ~10 minute connection closes.
    session_resumption=types.SessionResumptionConfig(),
    # Retain recent turns and discard older ones past the trigger; this is not summarization.
    context_window_compression=types.ContextWindowCompressionConfig(
        trigger_tokens=100_000, sliding_window=types.SlidingWindow(target_tokens=80_000)),
)


@dataclass
class Captions:
    """What a voice UI shows: finished lines per speaker, the line in progress and the mic state."""
    lines: list = field(default_factory=list)
    live: str = ""
    state: str = "listening"
    audio_bytes: int = 0

    def apply(self, row: dict) -> None:
        if row.get("interrupted"):
            self.state, self.live = "interrupted", ""  # stop playback and drop the unfinished line
        for side, who in (("input_transcription", "user"), ("output_transcription", "agent")):
            if side in row:
                if row.get("partial"):
                    self.live += row[side]["text"]  # a fragment; the finished event repeats it merged
                elif row[side]["text"]:
                    self.lines.append((who, row[side]["text"].strip()))
                    self.live = ""
        if row.get("audio_bytes"):
            self.state, self.audio_bytes = "speaking", self.audio_bytes + row["audio_bytes"]
        if row.get("turn_complete"):
            self.state, self.live = "listening", ""


def build_agent(model=MODEL) -> Agent:
    # {asked?} renders from session state once per Live connection; it is empty on the first one.
    return Agent(name="docs_helper", model=model, instruction=(
        "You are the docs assistant. Answer from this page in short spoken sentences.\n"
        "Questions the caller already asked in this call: {asked?}\n\n" + DOCS))


def make_runner(agent) -> Runner:
    return Runner(app_name=APP, agent=agent, session_service=InMemorySessionService())


async def open_session(runner, session_id: str):
    """Get or create: a reconnecting client reuses its ADK session and therefore its history."""
    session = await runner.session_service.get_session(app_name=APP, user_id="dev", session_id=session_id)
    return session or await runner.session_service.create_session(app_name=APP, user_id="dev", session_id=session_id)


def stored(session) -> list:
    """What run_live persisted: one row per saved event, with the kinds of data it carries."""
    rows = []
    for event in session.events:
        parts = (event.content.parts or []) if event.content else []
        kinds = sorted({k for p in parts for k in ("text", "inline_data", "function_call") if getattr(p, k)})
        kinds += [k for k in ("input_transcription", "output_transcription", "usage_metadata") if getattr(event, k)]
        rows.append({"author": event.author, "kinds": kinds,
                     "text": (event.input_transcription or event.output_transcription or types.Transcription()).text})
    return rows


async def remember_questions(runner, session) -> list:
    """Copy the caller's saved questions into state, so the next connection's instruction has them."""
    asked = [e.input_transcription.text.strip() if e.input_transcription else e.content.parts[0].text
             for e in session.events if e.author == "user" and (e.input_transcription or e.content)]
    await runner.session_service.append_event(session, Event(
        author="user", actions=EventActions(state_delta={"asked": "; ".join(asked)})))
    return asked
