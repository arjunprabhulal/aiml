"""Ask the docs assistant a question from Python and print every event it yields.

Run: python ask.py "How do I roll back production?" [--stream] [--max-llm-calls N]
"""
import argparse
import asyncio
from pathlib import Path
from dotenv import load_dotenv

from google.adk import Event, Runner
from google.adk.agents import RunConfig
from google.adk.agents.run_config import StreamingMode
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from docs_assistant.agent import root_agent

APP, USER = "docs", "dev"


def describe(event: Event) -> str:
    """One line per event: who wrote it, what kind it is, and its payload."""
    kind = "partial" if event.partial else "final" if event.is_final_response() else "event"
    parts = []
    for call in event.get_function_calls():
        parts.append(f"call {call.name}({call.args})")
    for result in event.get_function_responses():
        parts.append(f"result {result.name} -> {sorted(result.response)}")
    if event.content and not parts:
        parts.append(repr("".join(p.text or "" for p in event.content.parts if not p.thought)))
    return f"{event.author:<15} {kind:<8} {' '.join(parts)}"


async def ask(runner: Runner, session_id: str, question: str, config: RunConfig) -> list[Event]:
    """Send one user message and collect the events of that invocation, in order."""
    message = types.Content(role="user", parts=[types.Part(text=question)])
    events = []
    async for event in runner.run_async(user_id=USER, session_id=session_id, new_message=message,
                                        run_config=config, yield_user_message=True):
        events.append(event)
    return events


def answer(events: list[Event]) -> str:
    """The answer is the text of the agent's last final response, not every text chunk.

    is_final_response() is also True for the user's own message, so filter by author.
    """
    final = [e for e in events if e.is_final_response() and e.author != "user" and e.content]
    return "".join(p.text or "" for p in final[-1].content.parts if not p.thought) if final else ""


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--stream", action="store_true", help="stream text chunks as partial events")
    parser.add_argument("--max-llm-calls", type=int, default=10)
    args = parser.parse_args()

    sessions = InMemorySessionService()
    runner = Runner(app_name=APP, agent=root_agent, session_service=sessions)
    session = await sessions.create_session(app_name=APP, user_id=USER)
    config = RunConfig(streaming_mode=StreamingMode.SSE if args.stream else StreamingMode.NONE,
                       max_llm_calls=args.max_llm_calls)
    try:
        events = await ask(runner, session.id, args.question, config)
    finally:
        await runner.close()
    for event in events:
        print(describe(event))
    stored = await sessions.get_session(app_name=APP, user_id=USER, session_id=session.id)
    print(f"yielded {len(events)} events, session stores {len(stored.events)}")
    print("answer:", answer(events))


if __name__ == "__main__":
    asyncio.run(main())
