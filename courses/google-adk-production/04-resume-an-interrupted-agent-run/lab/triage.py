"""File a docs issue from a developer's report, and resume the run if the process dies mid-tool.

Run from this folder with GOOGLE_API_KEY set:
    python triage.py start "The tokens page says deploy tokens never expire. File a docs issue."
    python triage.py resume SESSION_ID INVOCATION_ID
--crash-after-write is fault injection: the process exits inside file_issue, after the tracker
write and before ADK records the tool's result. Set DOCS_MODEL=ollama_chat/gemma4:e2b for Gemma.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path

from filelock import FileLock

from google.adk import Agent, Runner
from google.adk.apps import App, ResumabilityConfig
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import DatabaseSessionService
from google.adk.tools.tool_context import ToolContext
from google.genai import types

HERE = Path(__file__).resolve().parent
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
DB_URL = os.environ.get("DOCS_DB", f"sqlite+aiosqlite:///{HERE / 'sessions.db'}")
TRACKER = Path(os.environ.get("DOCS_TRACKER", HERE / "tracker.json"))  # stands in for the issue tracker's API
APP, USER = "docs_triage", "dev-1"
FAULTS = {"crash_after_write": False, "idempotency_key": True}


def read_page(page: str) -> dict:
    """Read one page of the docuctl documentation: config, deploy, rollback or tokens."""
    if page not in {"config", "deploy", "rollback", "tokens"}:
        return {"error": f"No page {page!r}."}
    path = HERE / "docs" / f"{page}.md"
    return {"page": page, "text": path.read_text(encoding="utf-8")} if path.is_file() else {"error": f"No page {page!r}."}


def file_issue(title: str, body: str, tool_context: ToolContext) -> dict:
    """File one issue against the docs in the team tracker.

    Args:
        title: A short summary of the problem.
        body: What the page says and what is wrong.
    """
    # The stored call event supplies the same ID when a killed invocation is resumed.
    key = tool_context.function_call_id if FAULTS["idempotency_key"] else None
    if FAULTS["idempotency_key"] and not key:
        raise ValueError("file_issue requires a function call ID")
    with FileLock(str(TRACKER) + ".lock", timeout=10):
        issues = json.loads(TRACKER.read_text(encoding="utf-8")) if TRACKER.exists() else []
        for issue in issues:
            if key and issue["key"] == key:
                return {"issue": issue["number"], "duplicate_request": True}
        issue = {"number": len(issues) + 1, "key": key, "title": title, "body": body}
        pending = TRACKER.with_suffix(".pending")
        pending.write_text(json.dumps(issues + [issue], indent=2) + "\n", encoding="utf-8")
        os.replace(pending, TRACKER)

    if FAULTS["crash_after_write"]:
        os._exit(137)  # like a SIGKILL: no exception, no cleanup, nothing more is written to the session
    return {"issue": issue["number"]}


root_agent = Agent(
    name="docs_triage",
    model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
    instruction="""You triage reports about the docuctl documentation.
Read the page the report is about with read_page once, then file exactly one issue with file_issue
that quotes what the page says. Reply with the issue number in one sentence.""",
    tools=[read_page, file_issue],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
)

# Resumability is an App setting: the runner records which agent and tool steps finished.
app = App(name=APP, root_agent=root_agent, resumability_config=ResumabilityConfig(is_resumable=True))


def describe(event) -> str:
    parts = event.content.parts if event.content and event.content.parts else []
    what = [f"call {p.function_call.name}" if p.function_call else
            f"result {p.function_response.name} {json.dumps(p.function_response.response)[:60]}" if p.function_response else
            repr(p.text[:60]) for p in parts if p.function_call or p.function_response or (p.text and not p.thought)]
    if event.actions.end_of_agent:
        what.append("end_of_agent")
    return f"{event.author:<12} {' + '.join(what) or '(no parts)'}"


async def run(session_id: str | None, text: str | None = None, invocation_id: str | None = None) -> list:
    sessions = DatabaseSessionService(db_url=DB_URL)
    runner = Runner(app=app, session_service=sessions)
    if session_id is None:
        session_id = (await sessions.create_session(app_name=APP, user_id=USER)).id
        print("session", session_id, flush=True)
    message = types.Content(role="user", parts=[types.Part(text=text)]) if text else None
    events = []
    try:
        async for event in runner.run_async(user_id=USER, session_id=session_id, new_message=message, invocation_id=invocation_id):
            if not events:
                print("invocation", event.invocation_id, flush=True)
            events.append(event)
            print(describe(event), flush=True)
    finally:
        await runner.close()
    return events


async def check_resumable(sessions, session_id: str, invocation_id: str) -> None:
    """Refuse a resume that would start a new model turn instead of finishing an interrupted one."""
    session = await sessions.get_session(app_name=APP, user_id=USER, session_id=session_id)
    if session is None:
        raise SystemExit(f"no session {session_id}")
    mine = [e for e in session.events if e.invocation_id == invocation_id]
    if not mine:
        raise SystemExit(f"invocation {invocation_id} is not in session {session_id}")
    if any(e.actions.end_of_agent and e.author == root_agent.name for e in mine):
        raise SystemExit(f"invocation {invocation_id} already finished")


async def resume(session_id: str, invocation_id: str) -> list:
    await check_resumable(DatabaseSessionService(db_url=DB_URL), session_id, invocation_id)
    return await run(session_id, invocation_id=invocation_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    start_cmd = sub.add_parser("start")
    start_cmd.add_argument("report")
    start_cmd.add_argument("--crash-after-write", action="store_true")
    start_cmd.add_argument("--no-idempotency-key", action="store_true")
    resume_cmd = sub.add_parser("resume")
    resume_cmd.add_argument("session_id")
    resume_cmd.add_argument("invocation_id")
    resume_cmd.add_argument("--no-idempotency-key", action="store_true")
    args = parser.parse_args()
    FAULTS["crash_after_write"] = getattr(args, "crash_after_write", False)
    FAULTS["idempotency_key"] = not args.no_idempotency_key
    if args.command == "start":
        asyncio.run(run(None, text=args.report))
    else:
        asyncio.run(resume(args.session_id, args.invocation_id))


if __name__ == "__main__":
    main()
