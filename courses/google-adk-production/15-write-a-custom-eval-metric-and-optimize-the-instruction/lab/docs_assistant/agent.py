"""The docs assistant before optimization: its instruction says nothing about citations."""
import os
from pathlib import Path

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
DOCS = Path(__file__).resolve().parent / "docs"
INSTRUCTION = "You answer questions about the docs-assistant project. Use the tools to look things up."
# To evaluate an optimized instruction without editing this file: DOCS_INSTRUCTION_FILE=optimized-instruction.txt
if os.environ.get("DOCS_INSTRUCTION_FILE"):
    INSTRUCTION = Path(os.environ["DOCS_INSTRUCTION_FILE"]).read_text(encoding="utf-8").strip()


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
    instruction=INSTRUCTION,
    tools=[list_pages, read_page],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
)
