"""A live graph workflow: an intake agent finds the page and question, then an answer agent replies."""
import os
from pathlib import Path

from google.adk.agents import Agent
from google.adk.workflow import START, Workflow
from pydantic import BaseModel, Field

DOCS = Path(__file__).parent / "docs"
PAGES = sorted(p.name for p in DOCS.glob("*.md"))
# Every runnable Live lab uses the same model; the saved workflow receipt keeps its original model id.
WORKFLOW_MODEL = os.getenv("LIVE_MODEL", "gemini-3.8-live")


class DocsQuestion(BaseModel):
    """The typed handoff from intake to answer."""
    page: str = Field(description=f"One of: {', '.join(PAGES)}")
    question: str = Field(description="The caller's question, in their words")


def build_workflow(model=WORKFLOW_MODEL, answer_mode="task") -> Workflow:
    intake = Agent(name="intake", model=model, mode="task", output_schema=DocsQuestion, instruction=(
        f"You take calls for the docs assistant. Find out which page the caller means ({', '.join(PAGES)}) "
        "and what they want to know. Ask one short question per turn. Finish your task as soon as you have both."))
    pages = "\n\n".join((DOCS / name).read_text() for name in PAGES)
    answer = Agent(name="answer", model=model, mode=answer_mode, instruction=(
        "Answer the caller's question in one or two spoken sentences, only from these pages, "
        "then finish your task.\n\n" + pages))
    # Every node that speaks needs mode="task" or "chat"; single_turn runs outside the live connection.
    return Workflow(name="docs_call", edges=[(START, intake), (intake, answer)])


def transcript_by_node(rows) -> dict:
    """What each node said. A node that ends with finish_task can stop before its finished transcript
    arrives, so fall back to its partial fragments."""
    finished, fragments = {}, {}
    for row in rows:
        if "output_transcription" in row:
            target = fragments if row.get("partial") else finished
            target.setdefault(row["author"], []).append(row["output_transcription"]["text"])
    return {author: " ".join(t.strip() for t in finished[author]) if author in finished
            else "".join(fragments[author]).strip() + " [partial]" for author in {**fragments, **finished}}
