"""Run the docs assistant on Agent Platform Sessions and Memory Bank, and record what happens.

Usage: AGENT_ENGINE_ID=<id> python record.py
Needs ADC (gcloud auth application-default login), GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION.
"""
import asyncio
import json
import os
import re
import time
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models.google_llm import Gemini
from google.adk.sessions import InMemorySessionService, VertexAiSessionService
from google.genai import types

from docs_helper.agent import root_agent

HERE = Path(__file__).resolve().parent
PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ["GOOGLE_CLOUD_LOCATION"]
ENGINE = os.environ["AGENT_ENGINE_ID"]
APP = ENGINE  # with Agent Platform Sessions, the app name is the Agent Runtime instance
USER = os.environ.get("DOCS_USER", "dana")
out, record = [], {"model": "gemini-3.8-flash", "location": LOCATION, "failures": {}}


def redact(text: str) -> str:
    return re.sub(r"projects/\d+/", "projects/PROJECT_NUMBER/", str(text))


def log(line: str = "") -> None:
    out.append(redact(line))
    print(redact(line))


def summary(events) -> list[str]:
    lines = []
    for event in events:
        lines += [f"call   {c.name} {json.dumps(c.args)}" for c in event.get_function_calls()]
        for r in event.get_function_responses():
            body = r.response if r.name == "load_memory" else sorted(r.response)
            text = json.dumps(body, default=lambda o: o.model_dump(mode="json", exclude_none=True))
            lines.append(f"result {r.name} {redact(text)[:300]}")
        if event.is_final_response() and event.content:
            lines.append("answer " + "".join(p.text or "" for p in event.content.parts if not p.thought).strip())
    return lines


async def turn(runner: Runner, session_id: str, text: str) -> list:
    message = types.Content(role="user", parts=[types.Part(text=text)])
    return [e async for e in runner.run_async(user_id=USER, session_id=session_id, new_message=message)]


async def failures() -> None:
    # 1. Record the failure from using the session region for the model request.
    regional = Agent(name="docs_helper", model=Gemini(model="gemini-3.8-flash", client_kwargs={"location": LOCATION}),
                     instruction="Answer in one word.")
    runner = Runner(app_name="docs", agent=regional, session_service=InMemorySessionService())
    session = await runner.session_service.create_session(app_name="docs", user_id=USER)
    try:
        await turn(runner, session.id, "Say ok.")
    except Exception as error:  # noqa: BLE001 - record whatever the API raised
        record["failures"]["model_region"] = f"{type(error).__name__}: {redact(error)[:400]}"
    # 2. A Sessions service with no instance id and an ADK-style app name.
    try:
        await VertexAiSessionService(project=PROJECT, location=LOCATION).create_session(app_name="docs_helper", user_id=USER)
    except ValueError as error:
        record["failures"]["app_name"] = f"ValueError: {error}"
    for name, text in record["failures"].items():
        log(f"# failure {name}\n{text}\n")


async def require_empty() -> None:
    """Refuse an already-used instance instead of deleting its memories or sessions."""
    import vertexai
    client = vertexai.Client(project=PROJECT, location=LOCATION)
    name = f"projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{ENGINE}"
    if any(client.agent_engines.memories.list(name=name)):
        raise RuntimeError("Use a fresh lesson instance; existing memories will not be deleted.")
    sessions = VertexAiSessionService(PROJECT, LOCATION, ENGINE)
    if (await sessions.list_sessions(app_name=APP, user_id=USER)).sessions:
        raise RuntimeError("Use a fresh lesson instance; existing sessions will not be deleted.")


async def main() -> None:
    await require_empty()
    await failures()
    sessions = VertexAiSessionService(PROJECT, LOCATION, ENGINE)
    memory = VertexAiMemoryBankService(PROJECT, LOCATION, ENGINE)
    runner = Runner(app_name=APP, agent=root_agent, session_service=sessions, memory_service=memory)

    # Conversation 1: Dana says which version she runs.
    s1 = await sessions.create_session(app_name=APP, user_id=USER)
    log(f"# conversation 1 · session {s1.id}")
    log("> I run docuctl 1.x. How do I undo release r42 in production?")
    for line in summary(await turn(runner, s1.id, "I run docuctl 1.x. How do I undo release r42 in production?")):
        log(line)
    stored = await sessions.get_session(app_name=APP, user_id=USER, session_id=s1.id)
    record["session_1"] = {"id": s1.id, "stored_events": len(stored.events),
                           "authors": [e.author for e in stored.events]}

    # IngestEvents returns at once; Memory Bank extracts memories in the background.
    # force_flush asks it to process this conversation now instead of on its own trigger.
    started = time.monotonic()
    await memory.add_events_to_memory(app_name=APP, user_id=USER, events=stored.events, session_id=s1.id,
                                      custom_metadata={"force_flush": True})
    record["ingest_return_seconds"] = round(time.monotonic() - started, 2)
    early = await memory.search_memory(app_name=APP, user_id=USER, query="docuctl version")
    record["memories_right_after_ingest"] = len(early.memories)
    log(f"\n# ingest returned in {record['ingest_return_seconds']} s; search right after: {len(early.memories)} memories")
    found = early
    while not found.memories and time.monotonic() - started < 180:
        await asyncio.sleep(3)
        found = await memory.search_memory(app_name=APP, user_id=USER, query="docuctl version")
    record["searchable_after_seconds"] = round(time.monotonic() - started)
    record["memories"] = ["".join(p.text or "" for p in m.content.parts) for m in found.memories]
    log(f"# searchable after about {record['searchable_after_seconds']} s:")
    for text in record["memories"]:
        log(f"  - {text}")

    # Conversation 2: a new session; the version is not in it.
    s2 = await sessions.create_session(app_name=APP, user_id=USER)
    log(f"\n# conversation 2 · session {s2.id}")
    log("> How do I undo the last production release?")
    lines = summary(await turn(runner, s2.id, "How do I undo the last production release?"))
    for line in lines:
        log(line)
    record["session_2"] = {"id": s2.id, "lines": lines}
    listed = await sessions.list_sessions(app_name=APP, user_id=USER)
    record["sessions_listed"] = len(listed.sessions)
    log(f"\n# list_sessions for {USER}: {len(listed.sessions)} sessions")
    await runner.close()

    (HERE / "run-output.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    (HERE / "recorded-runs.json").write_text(redact(json.dumps(record, indent=2)) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
