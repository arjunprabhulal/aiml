"""A voice docs assistant: one Live agent, a queue for input and the run_live event stream."""
import asyncio
from pathlib import Path

from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from live_harness import MODEL, read_pcm, say_audio, say_text, spoken, talk

HERE = Path(__file__).parent
DOCS = (HERE / "docs/live-streaming.md").read_text()
APP = "voice_docs"

# Live models answer in audio only; the transcription is how text comes back.
RUN_CONFIG = RunConfig(response_modalities=["AUDIO"])


def build_agent(model=MODEL, grounded=True) -> Agent:
    instruction = "You are the docs assistant. Answer in one or two short spoken sentences."
    if grounded:
        instruction += " Answer only from this page; if it does not say, say so.\n\n" + DOCS
    return Agent(name="docs_helper", model=model, instruction=instruction)


async def ask(agent, turn, run_config=RUN_CONFIG):
    """Open one live session, send one turn, and return its events and the spoken answer."""
    runner = Runner(app_name=APP, agent=agent, session_service=InMemorySessionService())
    session = await runner.session_service.create_session(app_name=APP, user_id="dev")
    rows = await talk(runner, session.id, run_config, [turn])
    return rows, spoken(rows)


def mentions(answer: str, *facts: str) -> bool:
    """A minimal check: every expected fact appears in the transcript, ignoring case."""
    return all(fact.casefold() in answer.casefold() for fact in facts)


async def main():
    rows, answer = await ask(build_agent(), say_text("What does ADK stand for?"))
    print(f"[text turn] {answer}  (audio bytes: {sum(r.get('audio_bytes', 0) for r in rows)})")
    rows, answer = await ask(build_agent(), say_audio(read_pcm(HERE / "question.wav")))
    print(f"[heard] {spoken(rows, 'input_transcription')}\n[said] {answer}")


if __name__ == "__main__":
    asyncio.run(main())
