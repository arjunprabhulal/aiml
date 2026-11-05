"""Open a migrated session database and print each event's state delta.

Run: python check_migrated.py migrated.db
A migration that dropped an event's actions shows up here as an empty state_delta.
"""
import asyncio
import sys

from google.adk.sessions import DatabaseSessionService


async def check(path: str) -> list[str]:
    sessions = DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{path}")
    lines = []
    for listed in (await sessions.list_sessions(app_name="docs_assistant", user_id="dev-1")).sessions:
        session = await sessions.get_session(app_name="docs_assistant", user_id="dev-1", session_id=listed.id)
        lines.append(f"session {session.id}: {len(session.events)} events, state {dict(session.state)}")
        lines += [f"event {e.invocation_id} {e.author:<15} state_delta={dict(e.actions.state_delta)}" for e in session.events]
    return lines


if __name__ == "__main__":
    print("\n".join(asyncio.run(check(sys.argv[1]))))
