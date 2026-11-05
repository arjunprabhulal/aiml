"""A release bot, a second ADK agent, that asks the docs assistant through its MCP server.

McpToolset starts server.py over stdio and offers its one tool, prefixed docs_, to the bot's model.
Run with GOOGLE_API_KEY set: python release_bot.py "<question>"
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

HERE = Path(__file__).resolve().parent
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
QUESTION = "Staging deploy r42 failed in pre_deploy. Ask the docs whether rolling staging back undoes its migration."


def docs_toolset(timeout: float | None = 60) -> McpToolset:
    server = StdioServerParameters(
        command=sys.executable, args=[str(HERE / "server.py")], cwd=str(HERE),
        # The stdio client passes only HOME, PATH, SHELL, TERM, USER and LOGNAME to the server by default.
        env={"GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY", ""), "DOCS_MODEL": MODEL},
    )
    connection = StdioConnectionParams(server_params=server, **({"timeout": timeout} if timeout else {}))
    return McpToolset(connection_params=connection, tool_name_prefix="docs")


def make_bot(toolset: McpToolset) -> Agent:
    return Agent(
        name="release_bot",
        model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
        instruction="You help engineers with failed releases. For any question about how docuctl behaves, "
                    "call the docs tool with the full question, then answer in under 60 words.",
        tools=[toolset],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
    )


async def ask(question: str, timeout: float | None = 60) -> list:
    toolset = docs_toolset(timeout)
    runner = Runner(app_name="release", agent=make_bot(toolset), session_service=InMemorySessionService(),
                    auto_create_session=True)
    message = types.Content(role="user", parts=[types.Part(text=question)])
    try:
        return [e async for e in runner.run_async(user_id="ops", session_id="s1", new_message=message)]
    finally:
        try:
            await runner.close()
        finally:
            await toolset.close()


async def record(timeout: float | None, question: str = QUESTION) -> dict:
    events = await ask(question, timeout)
    answer = next(("".join(p.text or "" for p in e.content.parts if not p.thought).strip()
                   for e in reversed(events) if e.is_final_response() and e.content), "")
    return {"question": question, "timeout": timeout,
            "calls": [{"name": c.name, "args": c.args} for e in events for c in e.get_function_calls()],
            "results": [r.response for e in events for r in e.get_function_responses()], "answer": answer}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(record(60, " ".join(sys.argv[1:]) or QUESTION)), indent=2))
