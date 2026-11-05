"""Live tools for the docs assistant: a blocking search, a non-blocking export and a streaming link check."""
import asyncio
import os
import re
from pathlib import Path
from typing import AsyncGenerator

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.genai import types

# Use the current course model; historical 2.5/3.1 tool experiments remain in tools-run-historical.json.
TOOLS_MODEL = os.getenv("LIVE_MODEL", "gemini-3.8-live")

DOCS = Path(__file__).parent / "docs"
SLOW_S = 6.0  # the tests shorten this


def search_docs(query: str) -> dict:
    """Search the docs pages and rank matching lines by the number of query words they contain.

    Args:
      query: A few keywords, for example "connection minutes".
    """
    words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 3}
    scored = sorted(((sum(w in line.lower() for w in words), page.name, line.strip("- "))
                     for page in sorted(DOCS.glob("*.md")) for line in page.read_text().splitlines()), reverse=True)
    hits = [{"page": page, "line": line} for score, page, line in scored[:3] if score]
    return {"query": query, "hits": hits} if hits else {"query": query, "hits": [], "note": "no page mentions this"}


async def export_page_index() -> dict:
    """Export the list of docs pages for the search index. Takes several seconds."""
    await asyncio.sleep(SLOW_S)
    return {"status": "done", "pages": sorted(p.name for p in DOCS.glob("*.md"))}


async def check_links() -> AsyncGenerator[str, None]:
    """Count Markdown links in each docs page and report progress. This does not fetch or validate URLs."""
    pages = sorted(DOCS.glob("*.md"))
    for number, page in enumerate(pages, 1):
        await asyncio.sleep(SLOW_S / len(pages))
        links = re.findall(r"\]\(([^)]+)\)", page.read_text())
        yield f"Checked {page.name} ({number} of {len(pages)}): {len(links)} links."
    yield f"Done: {len(pages)} pages checked."


def stop_streaming(function_name: str):
    """Stop a running streaming tool. ADK intercepts this call by name.

    Args:
      function_name: The name of the streaming tool to stop.
    """


def build_agent(model=TOOLS_MODEL) -> Agent:
    lookup = FunctionTool(search_docs)
    # Gemini3.8 Live defaults to async function calls unless BLOCKING is explicit.
    lookup.behavior = types.Behavior.BLOCKING
    export = FunctionTool(export_page_index)
    # The Live API returns the result when the model is idle, instead of blocking the conversation.
    export.response_scheduling = types.FunctionResponseScheduling.WHEN_IDLE
    return Agent(name="docs_helper", model=model, tools=[lookup, export, check_links, FunctionTool(stop_streaming)],
                 instruction=("You are the docs assistant on a voice call. Look facts up with search_docs before you "
                              "answer, and answer in one or two short sentences. Start export_page_index or check_links "
                              "only when asked, call each once, and keep talking while they run."))
