"""The docs assistant on Gemini Enterprise Agent Platform: Gemini through Vertex, recall through Memory Bank."""
import os
from pathlib import Path

from google.adk import Agent
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import load_memory
from google.genai import types

DOCS = Path(__file__).resolve().parent / "docs"
PAGES = sorted(p.stem for p in DOCS.glob("*.md"))
# The recorded run uses global for this model. Sessions and Memory Bank stay regional
# (GOOGLE_CLOUD_LOCATION), so the model client gets its own location.
MODEL_LOCATION = os.environ.get("DOCS_MODEL_LOCATION", "global")


def read_page(page: str) -> dict:
    """Read one page of the docuctl documentation: config, deploy, rollback or tokens."""
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    return {"page": page, "text": (DOCS / f"{page}.md").read_text(encoding="utf-8")}


INSTRUCTION = """You answer questions from developers about docuctl, the team's deploy CLI.
Read the relevant page with read_page before you answer. Answers depend on the developer's
docuctl major version (1.x or 2.x). If the developer has not said it in this conversation,
call load_memory to look for it in earlier conversations before you ask. Keep the answer
under 80 words."""

def bounded_model_calls(callback_context, llm_request):
    """Limit each invocation before making another hosted request."""
    key = "temp:model_call_budget"
    budget = callback_context.state.get(key, {})
    if budget.get("invocation") != callback_context.invocation_id:
        budget = {"invocation": callback_context.invocation_id, "calls": 0}
    if budget["calls"] >= 4:
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text="The model call limit was reached; please narrow the question.")]))
    callback_context.state[key] = {**budget, "calls": budget["calls"] + 1}
    return None


root_agent = Agent(
    name="docs_helper",
    before_model_callback=bounded_model_calls,
    model=Gemini(model="gemini-3.8-flash", client_kwargs={"location": MODEL_LOCATION}),
    instruction=INSTRUCTION,
    tools=[read_page, load_memory],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, max_output_tokens=1024, thinking_config=types.ThinkingConfig(thinking_level="low")),
)

from google.adk.apps import App

app = App(root_agent=root_agent, name="docs_helper")
