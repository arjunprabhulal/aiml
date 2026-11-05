"""The guarded voice docs assistant: three checks around a Live agent that reads docs pages."""
import os
import re
from pathlib import Path
from typing import Any, Optional

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

DOCS = Path(__file__).parent / "docs"
PAGES = sorted(p.name for p in DOCS.glob("*.md"))
CORPUS = " ".join((DOCS / name).read_text() for name in PAGES)
# Use the same current model as the other Live labs; saved evaluations retain their original model.
MODEL = os.getenv("LIVE_MODEL", "gemini-3.8-live")
INJECTION = re.compile(r"ignore (all|your|previous) instructions|system prompt|reveal your instructions", re.I)
QUANTITY = re.compile(r"\b(\d+(?:\.\d+)?)\s*(kHz|minutes?|seconds?|attempts?)\b", re.I)


def say(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def read_page(name: str) -> dict:
    """Return the text of one docs page.

    Args:
      name: A page file name, for example "sessions.md".
    """
    return {"name": name, "text": (DOCS / name).read_text()}


def screen_input(callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]:
    """Input check: for speech it runs on the finished input transcript, after the model heard it."""
    text = " ".join(p.text or "" for c in llm_request.contents for p in c.parts or [])
    return say("I can only help with the docs pages.") if INJECTION.search(text) else None


def screen_output(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
    """Output check on the growing transcript: a quantity the pages do not contain stops the turn."""
    spoken = llm_response.output_transcription.text if llm_response.output_transcription else ""
    for number, unit in QUANTITY.findall(spoken or ""):
        if not re.search(rf"\b{re.escape(number)}\s*{unit[:3]}", CORPUS, re.I):
            callback_context.state["blocked_claim"] = f"{number} {unit}"
            return say("Let me check that against the docs page before I answer.")
    return None


def guard_page(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> Optional[dict]:
    """Tool check: read_page may open only the listed pages, never a path."""
    if tool.name == "read_page" and args.get("name") not in PAGES:
        return {"error": f"Unknown page {args.get('name')!r}. Pages: {', '.join(PAGES)}"}
    return None


root_agent = Agent(
    name="docs_voice", model=MODEL, tools=[read_page],
    instruction=(f"You are the docs assistant on a voice call. Pages: {', '.join(PAGES)}. Read the relevant page with "
                 "read_page before you answer, answer in one or two short sentences, and say so when a page "
                 "does not cover the question."),
    generate_content_config=types.GenerateContentConfig(safety_settings=[types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE)]),
    before_model_callback=screen_input, after_model_callback=screen_output, before_tool_callback=guard_page,
)
