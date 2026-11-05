"""The docs assistant under evaluation: it answers from the project's docs pages."""
from pathlib import Path

from google.adk import Agent
from google.genai import types

DOCS = Path(__file__).with_name("docs")


def list_pages() -> dict:
    """List the docs pages by path."""
    return {"pages": sorted(page.name for page in DOCS.glob("*.md"))}


def read_page(path: str) -> dict:
    """Return the Markdown of one docs page, by the path list_pages returned."""
    page = DOCS / path
    if page.parent != DOCS or not page.is_file():
        return {"error": f"No page {path!r}. Call list_pages for valid paths."}
    return {"path": path, "content": page.read_text()}


root_agent = Agent(
    name="docs_assistant",
    model="gemini-3.8-flash",  # or LiteLlm(model="ollama_chat/gemma4:e2b")
    generate_content_config=types.GenerateContentConfig(max_output_tokens=1024, thinking_config=types.ThinkingConfig(thinking_level="low")),
    instruction=("Answer questions about the docs-assistant project from its docs only. "
                 "Call list_pages, then read_page on the one page that answers. Reply in "
                 "one sentence and end it with the page path in parentheses. "
                 "For a rebuild question, include the command, that it drops the search index, "
                 "and that it builds the index again from the docs folder."),
    tools=[list_pages, read_page],
)
