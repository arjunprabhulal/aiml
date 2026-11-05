"""The docs assistant: it answers questions about the docs-assistant project from its docs pages."""
import os
from pathlib import Path

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
DOCS = Path(__file__).resolve().parent.parent / "docs"


def list_pages() -> dict:
    """List the docs pages by path."""
    return {"pages": sorted(page.name for page in DOCS.glob("*.md"))}


def read_page(path: str) -> dict:
    """Return the Markdown of one docs page, by the path list_pages returned."""
    page = DOCS / path
    if page.parent != DOCS or not page.is_file():
        return {"error": f"No page {path!r}. Call list_pages for valid paths."}
    return {"path": path, "content": page.read_text(encoding="utf-8")}


root_agent = Agent(
    name="docs_assistant",
    model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
    instruction=("Answer questions about the docs-assistant project from its docs only. "
                 "Call list_pages, then read_page on the one page that answers. Reply in "
                 "one sentence and end it with the page path in parentheses."),
    tools=[list_pages, read_page],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
)
