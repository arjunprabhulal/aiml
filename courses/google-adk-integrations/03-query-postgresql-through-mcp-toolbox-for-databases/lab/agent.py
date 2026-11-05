"""The docs assistant reading the docs analytics database through MCP Toolbox for Databases."""
import asyncio
import os
import sys

from google.adk import Agent, Runner
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.adk.tools.toolbox_toolset import ToolboxToolset
from google.genai import types

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
TOOLBOX_URL = os.environ.get("TOOLBOX_URL", "http://127.0.0.1:5000")
TEAM = "platform-docs"  # demo value; a service must derive this from an authorized identity


def docs_db(url: str = TOOLBOX_URL, toolset: str = "docs-reader", bind_team: bool = True) -> ToolboxToolset:
    """Only the docs-reader toolset; team is supplied here and omitted from the model-facing declaration."""
    return ToolboxToolset(server_url=url, toolset_name=toolset, bound_params={"team": TEAM} if bind_team else None)


def build_agent(model=None, toolset: ToolboxToolset | None = None) -> Agent:
    return Agent(
        name="docs_assistant",
        model=model or (LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL),
        instruction="You help the platform-docs team decide which pages to fix. Answer from the docs analytics "
                    "database tools only, and quote reader comments exactly. Today is 2026-10-21. "
                    "Say plainly when you cannot do something with your tools.",
        tools=[toolset or docs_db()],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
    )


async def ask(text: str, agent: Agent | None = None) -> list:
    sessions = InMemorySessionService()
    runner = Runner(app_name="docs", agent=agent or build_agent(), session_service=sessions)
    try:
        session = await sessions.create_session(app_name="docs", user_id="dev")
        message = types.Content(role="user", parts=[types.Part(text=text)])
        return [e async for e in runner.run_async(user_id="dev", session_id=session.id, new_message=message)]
    finally:
        await runner.close()


def show(events: list) -> str:
    lines = []
    for event in events:
        for call in event.get_function_calls():
            lines.append(f"call   {call.name} {call.args}")
        for result in event.get_function_responses():
            lines.append(f"result {result.name} {result.response}")
        if event.is_final_response() and event.author != "user" and event.content:
            lines.append("answer " + "".join(p.text or "" for p in event.content.parts if not p.thought).strip())
    return "\n".join(lines)


async def list_tools(url: str = TOOLBOX_URL, toolset: str = "docs-reader", bind_team: bool = True) -> list[str]:
    tools = docs_db(url, toolset, bind_team)
    try:
        return [tool.name for tool in await tools.get_tools()]
    finally:
        await tools.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["--tools"]:
        print(asyncio.run(list_tools()))
    else:
        print(show(asyncio.run(ask(" ".join(sys.argv[1:])))))
