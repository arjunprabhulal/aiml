"""An ambient docs reviewer: a docs-changed event arrives, the agent reads the page and posts a review."""
import json
import os
from pathlib import Path

from filelock import FileLock

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.tool_context import ToolContext
from google.genai import types

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
HERE = Path(__file__).resolve().parent.parent
REVIEWS = Path(os.environ.get("DOCS_REVIEWS", HERE / "reviews.jsonl"))  # the output channel nobody watches live


def read_page(page: str) -> dict:
    """Read one page of the docuctl documentation: config, deploy, rollback or tokens."""
    if page not in {"config", "deploy", "rollback", "tokens"}:
        return {"error": f"No page {page!r}."}
    path = HERE / "docs" / f"{page}.md"
    return {"page": page, "text": path.read_text(encoding="utf-8")} if path.is_file() else {"error": f"No page {page!r}."}


def post_review(page: str, summary: str, tool_context: ToolContext) -> dict:
    """Post the review of a changed docs page to the docs team's review log.

    Args:
        page: The page that changed.
        summary: One sentence on what a developer must know about the page.
    """
    # Trigger endpoints store the delivery (source, message ID) in session state. A redelivered
    # message runs in a new session, so dedupe on the message ID where the side effect happens.
    delivery = tool_context.state.get("trigger_delivery") or {}
    key = f"{delivery['source']}:{delivery['id']}" if delivery.get("source") and delivery.get("id") else None
    if not key:
        raise ValueError("post_review requires a trigger delivery ID")
    # All local processes must use this same lock path. This is not a remote API guarantee.
    with FileLock(str(REVIEWS) + ".lock", timeout=10):
        lines = REVIEWS.read_text(encoding="utf-8").splitlines() if REVIEWS.exists() else []
        if any(json.loads(line)["key"] == key for line in lines):
            return {"posted": False, "reason": "duplicate delivery"}
        with REVIEWS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "page": page, "summary": summary}) + "\n")
    return {"posted": True}


root_agent = Agent(
    name="docs_reviewer",
    model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
    description="Reviews docuctl docs pages when they change.",
    instruction="""You receive docs-change events as JSON: {"data": {"page": ..., "commit": ...}, "attributes": {...}}.
Read the changed page with read_page, then call post_review once with a one-sentence summary
of what a developer must know from that page. Then reply with the single word: done.""",
    tools=[read_page, post_review],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
)
