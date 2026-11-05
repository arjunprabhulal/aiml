"""Pin docs pages for a developer, then rewind the session to undo a turn.

Run from this folder with GOOGLE_API_KEY set: python pins.py
Sessions live in SQLite through DatabaseSessionService. Set DOCS_MODEL=ollama_chat/gemma4:e2b for Gemma.
"""
import asyncio
import os
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import DatabaseSessionService
from google.adk.tools.tool_context import ToolContext
from google.genai import types

HERE = Path(__file__).resolve().parent
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
DB_URL = os.environ.get("DOCS_DB", f"sqlite+aiosqlite:///{HERE / 'sessions.db'}")
APP, USER = "docs_assistant", "dev-1"
PAGES = ("config", "deploy", "rollback", "tokens")


async def pin_page(page: str, tool_context: ToolContext) -> dict:
    """Pin a docs page to the developer's reading list for this session.

    Args:
        page: The page name: config, deploy, rollback or tokens.
    """
    if page not in PAGES:
        return {"error": f"No page {page!r}."}
    pinned = [*tool_context.state.get("pinned", []), page]
    tool_context.state["pinned"] = pinned  # session-scoped state
    note = types.Part.from_bytes(data="\n".join(f"- {p}" for p in pinned).encode(), mime_type="text/markdown")
    version = await tool_context.save_artifact("reading-list.md", note)  # session-scoped artifact
    return {"pinned": pinned, "artifact_version": version}


def set_team(team: str, tool_context: ToolContext) -> dict:
    """Record the developer's team. It is kept for the user across all sessions.

    Args:
        team: The team name, for example payments or platform.
    """
    tool_context.state["user:team"] = team  # user-scoped state: the user: prefix
    return {"team": team}


root_agent = Agent(
    name=APP,
    model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
    instruction="""You keep a reading list of docuctl docs pages for a developer.
Use pin_page to pin pages and set_team when the developer names their team.
Current pins: {pinned?}. Developer's team: {user:team?}.
Answer in one short sentence.""",
    tools=[pin_page, set_team],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
)


def build_runner(db_url: str = DB_URL) -> Runner:
    return Runner(app_name=APP, agent=root_agent, session_service=DatabaseSessionService(db_url=db_url),
                  artifact_service=InMemoryArtifactService())


async def ask(runner: Runner, session_id: str, text: str) -> list:
    message = types.Content(role="user", parts=[types.Part(text=text)])
    return [e async for e in runner.run_async(user_id=USER, session_id=session_id, new_message=message)]


async def snapshot(runner: Runner, session_id: str) -> dict:
    """What the services hold now: session and user state, artifact versions, event count."""
    session = await runner.session_service.get_session(app_name=APP, user_id=USER, session_id=session_id)
    versions = await runner.artifact_service.list_versions(app_name=APP, user_id=USER, session_id=session_id,
                                                           filename="reading-list.md")
    latest = await runner.artifact_service.load_artifact(app_name=APP, user_id=USER, session_id=session_id,
                                                         filename="reading-list.md")
    return {"pinned": session.state.get("pinned"), "user:team": session.state.get("user:team"),
            "artifact_versions": versions, "artifact": latest.inline_data.data.decode() if latest else None,
            "events": len(session.events)}


async def main() -> None:
    runner = build_runner()
    session = await runner.session_service.create_session(app_name=APP, user_id=USER)
    try:
        first = await ask(runner, session.id, "I'm on the payments team. Pin the rollback page.")
        print("after turn 1:", await snapshot(runner, session.id))
        second = await ask(runner, session.id, "Pin the tokens page too. And I moved to the platform team.")
        print("after turn 2:", await snapshot(runner, session.id))
        await runner.rewind_async(user_id=USER, session_id=session.id,
                                  rewind_before_invocation_id=second[0].invocation_id)
        print("after rewind:", await snapshot(runner, session.id))
        third = await ask(runner, session.id, "Which pages are pinned, and which team am I on?")
        print("turn 3:", third[-1].content.parts[-1].text)
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
