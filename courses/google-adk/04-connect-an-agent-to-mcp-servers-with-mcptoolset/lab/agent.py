"""The docs assistant with the team's task tracker attached over MCP through McpToolset."""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from google.adk import Agent, Runner
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.adk.tools import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

HERE = Path(__file__).resolve().parent
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
PAGES = sorted(p.stem for p in (HERE / "docs").glob("*.md"))


def read_page(page: str) -> dict:
    """Read one page of the docuctl documentation: config, deploy, rollback or tokens."""
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    return {"page": page, "text": (HERE / "docs" / f"{page}.md").read_text(encoding="utf-8")}


def tracker(tool_filter: list[str] | None = ("list_tasks", "add_task"), python: str | None = None) -> McpToolset:
    """The task tracker MCP server as a child process; only the tools in tool_filter reach the model."""
    command = python or os.environ.get("TASKS_SERVER_PYTHON", sys.executable)
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(command=command, args=[str(HERE / "tasks_server.py")]),
            timeout=10,  # setup and default MCP request-response timeout in this SDK
        ),
        tool_filter=list(tool_filter) if tool_filter else None,
    )


def build_agent(model=None, toolset: McpToolset | None = None) -> Agent:
    return Agent(
        name="docs_assistant",
        model=model or (LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL),
        instruction="""You help developers keep the docuctl documentation correct.
Read pages with read_page. Track docs work in the task tracker: list the tasks before you add one,
and do not add a task that is already open. Say plainly when you cannot do something with your tools.""",
        tools=[read_page, toolset or tracker()],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, max_output_tokens=1024, thinking_config=types.ThinkingConfig(thinking_level="low")),
    )


async def ask(text: str, agent: Agent | None = None) -> list:
    """Run one question in a new session; closing the runner also stops the MCP server process."""
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
            r = result.response
            if "isError" in r:  # an MCP CallToolResult, passed through as the function response
                body = r.get("structuredContent") or " ".join(c.get("text", "") for c in r.get("content", []))
                lines.append(f"result {result.name} isError={r['isError']} {body}")
            else:
                lines.append(f"result {result.name} {sorted(r)}")
        if event.is_final_response() and event.author != "user" and event.content:
            lines.append("answer " + "".join(p.text or "" for p in event.content.parts if not p.thought).strip())
    return "\n".join(lines)


async def list_tools() -> list[str]:
    toolset = tracker()
    try:
        return [tool.name for tool in await toolset.get_tools()]
    finally:
        await toolset.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ask one question or discover local MCP tools without a model.")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--tools", action="store_true")
    options = parser.parse_args()
    if options.tools:
        if options.question is not None:
            parser.error("choose tool discovery or one question")
        print(asyncio.run(list_tools()))
    else:
        if options.question is None or not options.question.strip():
            parser.error("one nonempty question is required, or use --tools")
        print(show(asyncio.run(ask(options.question))))
