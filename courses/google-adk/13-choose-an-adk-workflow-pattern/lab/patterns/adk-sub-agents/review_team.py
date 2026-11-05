"""A docs-review coordinator that delegates to two single-turn sub-agents."""
import re
from typing import Literal

from google.adk import Agent
from google.genai import types
from pydantic import BaseModel

MODEL = "gemini-3.8-flash"  # or LiteLlm(model="ollama_chat/gemma4:e2b")


class PrSummary(BaseModel):
    title: str
    risk: Literal["low", "medium", "high"]
    pages: list[str]


class StyleReport(BaseModel):
    problems: list[str]


def find_long_sentences(text: str, limit: int = 30) -> dict:
    """Return the added sentences that have more than `limit` words."""
    added = " ".join(line[1:] for line in text.splitlines()
                     if line.startswith("+") and not line.startswith("+++"))
    sentences = re.split(r"(?<=[.!?])\s+", added)
    return {"long_sentences": [s for s in sentences if len(s.split()) > limit]}


def build_team(model=None, isolate=True) -> Agent:
    """isolate=True removes transfer_to_agent from the sub-agents (see the failure section)."""
    model = model or MODEL
    no_transfer = {"disallow_transfer_to_parent": isolate, "disallow_transfer_to_peers": isolate}
    pr_summarizer = Agent(
        name="pr_summarizer",
        model=model,
        generate_content_config=types.GenerateContentConfig(max_output_tokens=1024),
        mode="single_turn",
        description="Summarizes a docs diff: title, risk and changed pages.",
        instruction=("Summarize the diff. risk is high if the diff removes a section "
                     "that readers rely on, medium if it changes commands, otherwise low."),
        output_schema=PrSummary,
        **no_transfer,
    )
    style_checker = Agent(
        name="style_checker",
        model=model,
        generate_content_config=types.GenerateContentConfig(max_output_tokens=1024),
        mode="single_turn",
        description="Finds prose problems in the added lines of a docs diff.",
        instruction="Call find_long_sentences on the diff, then list each problem in one line.",
        tools=[find_long_sentences],
        output_schema=StyleReport,
        **no_transfer,
    )
    return Agent(
        name="docs_reviewer",
        model=model,
        generate_content_config=types.GenerateContentConfig(max_output_tokens=1024),
        instruction=("You review docs pull requests for the docs-assistant project. "
                     "Send the diff to pr_summarizer and to style_checker, then reply with "
                     "a review of at most five lines that uses both results."),
        sub_agents=[pr_summarizer, style_checker],
    )


def delegations(events: list[dict]) -> list[str]:
    """The sub-agents the coordinator called, in order, from the event stream."""
    names = {"pr_summarizer", "style_checker"}
    return [call["name"] for event in events if event["author"] == "docs_reviewer"
            for call in event.get("calls", []) if call["name"] in names]
