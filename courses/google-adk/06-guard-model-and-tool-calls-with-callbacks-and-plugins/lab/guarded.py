"""The docs assistant behind two guards: an app-wide secret-redaction plugin and a workspace check."""
import asyncio
import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv

from google.adk import Agent, Runner
from google.adk.apps import App
from google.adk.models.lite_llm import LiteLlm
from google.adk.plugins import BasePlugin
from google.adk.sessions import InMemorySessionService
from google.genai import types

WORKSPACE = Path(__file__).resolve().parent / "workspace"
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
AWS_KEY_ID = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")  # AWS access key IDs
REDACTED = "[REDACTED aws_access_key_id]"


def redact(text: str) -> tuple[str, int]:
    return AWS_KEY_ID.subn(REDACTED, text)


class RedactSecrets(BasePlugin):
    """App-wide: remove AWS key IDs from user messages and tool results before they are stored or sent."""

    def __init__(self) -> None:
        super().__init__(name="redact_secrets")
        self.redactions: list[str] = []  # where each redaction happened, for an audit log

    async def on_user_message_callback(self, *, invocation_context, user_message):
        changed = False
        parts = []
        for part in user_message.parts or []:
            if part.text:
                text, count = redact(part.text)
                changed |= count > 0
                self.redactions += ["user_message"] * count
                part = part.model_copy(update={"text": text})
            parts.append(part)
        return types.Content(role=user_message.role, parts=parts) if changed else None  # None keeps it

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
        if isinstance(result, dict) and isinstance(result.get("text"), str):
            text, count = redact(result["text"])
            if count:
                self.redactions += [f"tool:{tool.name}"] * count
                return {**result, "text": text}  # a dict replaces the tool result
        return None


def read_file(path: str) -> dict:
    """Read a text file from the repository workspace, for example docuctl.toml or docs/rollback.md."""
    target = WORKSPACE / path
    if not target.is_file():
        return {"error": f"No file {path}."}
    return {"path": path, "text": target.read_text(encoding="utf-8")}


def stay_in_workspace(tool, args: dict, tool_context) -> dict | None:
    """Agent callback: refuse a path that resolves outside the workspace, before the tool runs."""
    if tool.name != "read_file":
        return None
    resolved = (WORKSPACE / str(args.get("path", ""))).resolve()
    if not resolved.is_relative_to(WORKSPACE):  # a string prefix check would accept workspace-old/
        return {"error": f"Refused: {args.get('path')} is outside the workspace."}
    return None


root_agent = Agent(
    name="docs_assistant",
    model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
    instruction="""You help developers with docuctl and their repository. Read files with read_file;
the docuctl docs are in docs/. Check a config file against docs/config.md. Keep answers under 100 words.""",
    tools=[read_file],
    before_tool_callback=stay_in_workspace,
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, max_output_tokens=1024, thinking_config=types.ThinkingConfig(thinking_level="low")),
)


def build_app(agent: Agent = root_agent, plugins: list[BasePlugin] | None = None, *, app_name: str = "docs") -> App:
    """Plugins on the App apply to every agent, tool and model call the runner makes."""
    return App(name=app_name, root_agent=agent, plugins=[RedactSecrets()] if plugins is None else plugins)


async def ask(app: App, text: str) -> tuple[list, list]:
    """Run one question; return the events and the events the session stored."""
    sessions = InMemorySessionService()
    runner = Runner(app=app, session_service=sessions)
    try:
        session = await sessions.create_session(app_name=app.name, user_id="dev")
        message = types.Content(role="user", parts=[types.Part(text=text)])
        events = [e async for e in runner.run_async(user_id="dev", session_id=session.id, new_message=message)]
        stored = await sessions.get_session(app_name=app.name, user_id="dev", session_id=session.id)
        return events, stored.events
    finally:
        await runner.close()


def show(events: list) -> str:
    lines = []
    for event in events:
        lines += [f"call   {c.name} {c.args}" for c in event.get_function_calls()]
        lines += [f"result {r.name} {r.response.get('error') or sorted(r.response)}" for r in event.get_function_responses()]
        if event.is_final_response() and event.author != "user" and event.content:
            lines.append("answer " + "".join(p.text or "" for p in event.content.parts if not p.thought).strip())
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ask one question through the full guarded App.")
    parser.add_argument("question")
    options = parser.parse_args()
    if not options.question.strip():
        parser.error("one nonempty question is required")
    print(show(asyncio.run(ask(build_app(), options.question))[0]))
