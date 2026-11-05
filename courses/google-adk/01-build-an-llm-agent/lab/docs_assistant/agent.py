"""Answer developer questions from a small, bundled docuctl guide."""
import os
from pathlib import Path

from google.adk.agents import Agent
from google.genai import types

GUIDE = Path(__file__).with_name("docuctl.md").read_text(encoding="utf-8")

root_agent = Agent(
    name="docs_assistant",
    model=os.environ.get("DOCS_MODEL", "gemini-3.8-flash"),
    description="Explains docuctl commands from the bundled guide.",
    instruction=(
        "Help a developer use docuctl, a fictional deployment CLI. "
        "Answer only from the guide below. Copy commands exactly in backticks. "
        "If the guide does not answer the question, say that it does not cover it. "
        "Keep the answer under 100 words. Explain commands; do not claim to run them.\n\n"
        "<guide>\n" + GUIDE + "\n</guide>"
    ),
    generate_content_config=types.GenerateContentConfig(
        max_output_tokens=1024,
        thinking_config=types.ThinkingConfig(thinking_level="low"),
    ),
)
