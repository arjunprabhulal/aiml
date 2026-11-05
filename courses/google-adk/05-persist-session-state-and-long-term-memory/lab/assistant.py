"""The docs assistant with a persistent session store, user state and long-term memory."""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from typing import Literal

from google.adk import Agent, Runner
from google.adk.memory import InMemoryMemoryService
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import DatabaseSessionService
from google.adk.tools import ToolContext, load_memory
from google.genai import types

HERE = Path(__file__).resolve().parent
APP = "docs"
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
DB_URL = os.environ.get("DOCS_DB", f"sqlite+aiosqlite:///{HERE / 'sessions.db'}")
PAGES = sorted(p.stem for p in (HERE / "docs").glob("*.md"))


def read_page(page: str) -> dict:
    """Read one page of the docuctl documentation: config, deploy, rollback or tokens."""
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    return {"page": page, "text": (HERE / "docs" / f"{page}.md").read_text(encoding="utf-8")}


def set_docuctl_version(version: Literal["1.x", "2.x"], tool_context: ToolContext) -> dict:
    """Remember which docuctl version the developer uses, for this and later conversations."""
    tool_context.state["user:docuctl_version"] = version  # user: state is shared by the user's sessions
    return {"saved": version}


INSTRUCTION = """You answer questions from developers about docuctl, the team's deploy CLI.
The developer's docuctl version: {user:docuctl_version?}
When the developer says which version they use, call set_docuctl_version first.
If the version is empty and the answer depends on it, ask for it. Read the relevant page with
read_page and answer for the developer's version. When the developer refers to an earlier
conversation, call load_memory. Keep the answer under 80 words."""

root_agent = Agent(
    name="docs_assistant",
    model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
    instruction=INSTRUCTION,
    tools=[read_page, set_docuctl_version, load_memory],
    output_key="last_answer",  # the final reply is also saved to session state
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, max_output_tokens=1024, thinking_config=types.ThinkingConfig(thinking_level="low")),
)


def make_runner(memory: InMemoryMemoryService, agent: Agent = root_agent, db_url: str = DB_URL) -> Runner:
    """A runner whose sessions live in a database; memory is a separate, searchable store."""
    return Runner(app_name=APP, agent=agent, session_service=DatabaseSessionService(db_url=db_url),
                  memory_service=memory)


async def ask(runner: Runner, user_id: str, session_id: str, text: str) -> list:
    message = types.Content(role="user", parts=[types.Part(text=text)])
    return [e async for e in runner.run_async(user_id=user_id, session_id=session_id, new_message=message)]


def show(events: list) -> str:
    lines = []
    for event in events:
        lines += [f"call   {c.name} {c.args}" for c in event.get_function_calls()]
        lines += [f"result {r.name} {sorted(r.response)}" for r in event.get_function_responses()]
        if event.actions.state_delta:
            lines.append(f"state  {event.actions.state_delta}")
        if event.is_final_response() and event.author != "user" and event.content:
            lines.append("answer " + "".join(p.text or "" for p in event.content.parts if not p.thought).strip())
    return "\n".join(lines)


async def main(user_id: str, text: str) -> None:
    runner = make_runner(InMemoryMemoryService())
    session = await runner.session_service.create_session(app_name=APP, user_id=user_id)
    print(show(await ask(runner, user_id, session.id, text)))
    await runner.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], " ".join(sys.argv[2:])))
