"""The docs assistant with typed tools, argument validation and approval for writes."""
import asyncio
import functools
import inspect
import os
from pathlib import Path
from dotenv import load_dotenv
import sys
import typing
from typing import Callable

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from google.adk import Agent, Runner
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

import docs_tools

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
CONFIRM = "adk_request_confirmation"
INSTRUCTION = """You help developers with the docuctl documentation.
Search and read pages before you answer or file an issue. File an issue only when the user asks.
If a tool returns an error, fix the arguments and call it again, or explain what went wrong.
If the user rejects a call, do not make it again; say that nothing was filed."""


@functools.cache
def arguments_model(func) -> type[BaseModel]:
    """A Pydantic model of the function's parameters, Field constraints included."""
    hints = typing.get_type_hints(func, include_extras=True)
    fields = {name: (hints[name], ... if p.default is p.empty else p.default)
              for name, p in inspect.signature(func).parameters.items()}
    return create_model(f"{func.__name__}_args", __config__=ConfigDict(extra="forbid"), **fields)


def check_arguments(tool, args: dict, tool_context) -> dict | None:
    """Validate a call before it runs or asks for approval. A dict result replaces the call."""
    func = getattr(tool, "func", None)
    if func is None:
        return None
    try:
        arguments_model(func).model_validate(args)
    except ValidationError as error:
        problems = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()]
        return {"error": "Invalid arguments. " + "; ".join(problems)}
    return None  # None lets the call continue


def build_agent(model=None) -> Agent:
    return Agent(
        name="docs_assistant",
        model=model or (LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL),
        instruction=INSTRUCTION,
        before_tool_callback=check_arguments,
        tools=[
            docs_tools.search_docs,
            docs_tools.read_page,
            FunctionTool(docs_tools.file_docs_issue, require_confirmation=True),
        ],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_level="low")),
    )


Approver = Callable[[str, dict], bool]


async def ask(runner: Runner, session_id: str, text: str, approve: Approver) -> list:
    """Run one user turn. When a write asks for confirmation, let `approve` decide and resume."""
    events = []
    message = types.Content(role="user", parts=[types.Part(text=text)])
    while message:
        pending = []
        async for event in runner.run_async(user_id="dev", session_id=session_id, new_message=message):
            events.append(event)
            pending += [c for c in event.get_function_calls() if c.name == CONFIRM]
        replies = []
        for request in pending:
            call = request.args["originalFunctionCall"]
            replies.append(types.Part(function_response=types.FunctionResponse(
                id=request.id, name=CONFIRM, response={"confirmed": approve(call["name"], call["args"])})))
        message = types.Content(role="user", parts=replies) if replies else None
    return events


def answer_text(event) -> str:
    if not (event.is_final_response() and event.author != "user" and event.content):
        return ""
    return "".join(p.text for p in event.content.parts if p.text and not p.thought).strip()


async def main(text: str) -> None:
    sessions = InMemorySessionService()
    runner = Runner(app_name="docs", agent=build_agent(), session_service=sessions)
    session = await sessions.create_session(app_name="docs", user_id="dev")

    def approve(name: str, args: dict) -> bool:
        return input(f"Allow {name}({args})? [y/N] ").strip().lower() == "y"

    try:
        for event in await ask(runner, session.id, text, approve):
            for call in event.get_function_calls():
                print("call    ", call.name, call.args)
            for result in event.get_function_responses():
                print("result  ", result.name, result.response)
            if answer_text(event):
                print("answer  ", answer_text(event))
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "Find the rollback page and summarize it."))
