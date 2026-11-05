"""The docs assistant with one tool, so its event stream has calls, results and an answer."""
import os
from pathlib import Path

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
DOCS = Path(__file__).resolve().parent.parent / "docs"
PAGES = sorted(p.stem for p in DOCS.glob("*.md"))


def read_page(page: str) -> dict:
    """Read one page of the docuctl documentation.

    Args:
        page: The page name: config, deploy, rollback or tokens.
    """
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    return {"page": page, "text": (DOCS / f"{page}.md").read_text(encoding="utf-8")}


root_agent = Agent(
    name="docs_assistant",
    model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
    description="Answers developer questions about docuctl from its documentation.",
    instruction="""You answer questions from developers about docuctl, the team's deploy CLI.
Read the relevant page with read_page before you answer, and answer only from it.
Copy commands exactly, in backticks. Keep the answer under 100 words.""",
    tools=[read_page],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=1024,
        thinking_config=types.ThinkingConfig(thinking_level="low"),
    ),
)
