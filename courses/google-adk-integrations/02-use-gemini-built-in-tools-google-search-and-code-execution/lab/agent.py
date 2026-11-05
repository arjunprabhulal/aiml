"""The docs assistant with Gemini's built-in Google Search and code execution."""
import asyncio
import os
import sys
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.code_executors import BuiltInCodeExecutor
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig
from google.adk.tools import google_search
from google.genai import types

HERE = Path(__file__).resolve().parent
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")  # provider-hosted Gemini tools: no Ollama option
PAGES = sorted(p.stem for p in (HERE / "docs").glob("*.md"))


def read_page(page: str) -> dict:
    """Read one page of the docuctl documentation: dependencies or deploy-timings."""
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    root = (HERE / "docs").resolve()
    path = (root / f"{page}.md").resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return {"error": f"No readable docs page {page!r}."}
    return {"page": page, "text": path.read_text(encoding="utf-8")}


def build_agent(model=None, combine: bool = True, tools=None, code: bool = True) -> Agent:
    # Gemini runs google_search and code execution server-side. Mixing them with read_page, a function
    # tool, in one request needs include_server_side_tool_invocations (the API returns 400 without it).
    config = types.GenerateContentConfig(temperature=0.2, max_output_tokens=2048, thinking_config=types.ThinkingConfig(thinking_level="low"))
    if combine:
        config.tool_config = types.ToolConfig(include_server_side_tool_invocations=True)
    return Agent(
        name="docs_assistant",
        model=model or MODEL,
        instruction="You help developers keep the docuctl documentation correct. Read pages with read_page. "
                    "Use Google Search for facts that change, such as the latest release of a package. "
                    "Use code for any arithmetic or statistics. Say which page or source each fact comes from.",
        tools=tools if tools is not None else [read_page, google_search],
        code_executor=BuiltInCodeExecutor() if code else None,
        generate_content_config=config,
    )


async def ask(text: str, agent: Agent | None = None) -> list:
    sessions = InMemorySessionService()
    runner = Runner(app_name="docs", agent=agent or build_agent(), session_service=sessions)
    try:
        session = await sessions.create_session(app_name="docs", user_id="dev")
        message = types.Content(role="user", parts=[types.Part(text=text)])
        return [e async for e in runner.run_async(user_id="dev", session_id=session.id, new_message=message,
                                                run_config=RunConfig(max_llm_calls=6))]
    finally:
        await runner.close()


def sources(events: list) -> list[dict]:
    """The web sources Gemini grounded its answer on, from the last event that carries them."""
    grounded = [e.grounding_metadata for e in events if e.grounding_metadata and e.grounding_metadata.grounding_chunks]
    if not grounded:
        return []
    meta = grounded[-1]
    return [{"title": c.web.title, "uri": c.web.uri} for c in meta.grounding_chunks if c.web]


def citations(events: list) -> list[dict]:
    """Each answer segment with the sources Gemini says support it, from grounding_supports."""
    grounded = [e.grounding_metadata for e in events if e.grounding_metadata and e.grounding_metadata.grounding_supports]
    if not grounded:
        return []
    meta = grounded[-1]
    titles = [c.web.title if c.web else "?" for c in meta.grounding_chunks or []]
    return [{"text": s.segment.text, "sources": [titles[i] for i in s.grounding_chunk_indices or []]}
            for s in meta.grounding_supports]


def show(events: list) -> str:
    lines = []
    for event in events:
        for part in (event.content.parts if event.content else None) or []:
            if part.tool_call:  # a built-in tool Gemini ran server-side, returned because of the flag
                lines.append(f"server {part.tool_call.tool_type.name} {part.tool_call.args}")
            if part.function_call:
                lines.append(f"call   {part.function_call.name} {part.function_call.args}")
            if part.function_response:
                lines.append(f"result {part.function_response.name} {sorted(part.function_response.response)}")
            if part.executable_code:
                lines.append("code   " + part.executable_code.code.strip().replace("\n", "\n       "))
            if part.code_execution_result:
                result = part.code_execution_result
                lines.append(f"output {result.outcome.name} {(result.output or '').strip()}")
        meta = event.grounding_metadata
        if meta and meta.web_search_queries:
            lines.append(f"search {meta.web_search_queries}")
        if event.is_final_response() and event.author != "user" and event.content:
            text = "".join(p.text or "" for p in event.content.parts if p.text and not p.thought).strip()
            if text:
                lines.append("answer " + text)
    for source in sources(events):
        lines.append(f"source {source['title']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(show(asyncio.run(ask(" ".join(sys.argv[1:])))))
