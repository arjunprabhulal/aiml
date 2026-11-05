"""Build a v0 (pickle) session database like one written by ADK releases before 1.22.

Run: python legacy.py legacy.db
It uses ADK's own v0 schema classes; DatabaseSessionService detects the v0 tables and writes
event actions as pickles. The page_views Counter is session state that is not plain JSON data.
"""
import asyncio
import collections
import sys

from google.adk.events import Event, EventActions
from google.adk.sessions import DatabaseSessionService
from google.adk.sessions.schemas import v0
from google.genai import types
from sqlalchemy import create_engine


async def build(path: str) -> None:
    engine = create_engine(f"sqlite:///{path}")
    v0.Base.metadata.create_all(engine)  # the legacy tables, with no schema-version row
    engine.dispose()
    sessions = DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{path}")
    session = await sessions.create_session(app_name="docs_assistant", user_id="dev-1", session_id="pins-2025",
                                            state={"user:team": "payments"})
    turns = [("Pin the rollback page.", {"pinned": ["rollback"]}),
             ("Pin the tokens page.", {"pinned": ["rollback", "tokens"],
                                       "page_views": collections.Counter(rollback=3, tokens=1)})]
    for n, (text, delta) in enumerate(turns, start=1):
        await sessions.append_event(session, Event(invocation_id=f"e-{n}", author="user",
                                                   content=types.Content(role="user", parts=[types.Part(text=text)])))
        await sessions.append_event(session, Event(invocation_id=f"e-{n}", author="docs_assistant",
                                                   content=types.Content(role="model", parts=[types.Part(text="Pinned.")]),
                                                   actions=EventActions(state_delta=delta)))


if __name__ == "__main__":
    asyncio.run(build(sys.argv[1]))
