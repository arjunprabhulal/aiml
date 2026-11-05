"""Draft a release announcement with one agent and gate it with a second, reviewing agent."""
from typing import Literal

from google.adk import Agent, Event, Workflow
from google.genai import types
from pydantic import BaseModel, Field


class Changes(BaseModel):
    version: str
    entries: list[str]


class Draft(BaseModel):
    title: str
    body: str


class Review(BaseModel):
    verdict: Literal["approve", "reject"]
    unsupported: list[str] = Field(
        description="Each sentence of the draft that no changelog entry supports, copied exactly.")


def parse_changelog(node_input: str, version_in_facts: bool = True):
    """The first line is the version, each '- ' line is one entry.
    It also writes the facts the reviewer checks against to state."""
    lines = [line.strip() for line in node_input.strip().splitlines() if line.strip()]
    if not lines or not lines[0].startswith("## "):
        raise ValueError("changelog must start with a '## <version>' heading")
    entries = [line[2:] for line in lines[1:] if line.startswith("- ")]
    if not entries:
        raise ValueError(f"no entries under {lines[0]}")
    changes = Changes(version=lines[0][3:], entries=entries)
    facts = [f"- {e}" for e in entries]
    if version_in_facts:
        facts.insert(0, f"- docuctl {changes.version} is released.")
    return Event(output=changes, state={"changelog": "\n".join(facts)})


def gate(node_input: Review, draft: dict):
    """Router node: the reviewer's verdict picks the edge. A verdict that lists
    unsupported sentences is a rejection, whatever the verdict field says."""
    verdict = "reject" if node_input.unsupported else node_input.verdict
    return Event(route=verdict, output={"draft": draft, "unsupported": node_input.unsupported})


def publish(node_input: dict):
    draft = node_input["draft"]
    return Event(message=f"APPROVED\n# {draft['title']}\n\n{draft['body']}")


def send_back(node_input: dict):
    problems = "\n".join(f"- {s}" for s in node_input["unsupported"])
    return Event(message=f"REJECTED: the reviewer found claims with no changelog entry:\n{problems}")


WRITER = {
    "upbeat": ("Write a short release announcement for users of docuctl, the docs-site CLI. "
               "Make it upbeat and explain why each change matters to them. 3 to 5 sentences."),
    "factual": ("Write a short release announcement for users of docuctl, the docs-site CLI. "
                "Say what each entry changes, in plain words. Add no benefit, number or "
                "comparison that an entry does not state. 3 to 5 sentences."),
}


def build_workflow(model=None, style="factual", version_in_facts=True) -> Workflow:
    model = model or "gemini-3.8-flash"  # or LiteLlm(model="ollama_chat/gemma4:e2b")
    writer = Agent(
        name="write_announcement",
        model=model,
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)),
        input_schema=Changes,
        output_schema=Draft,
        output_key="draft",
        instruction=WRITER[style],
    )
    reviewer = Agent(
        name="review_announcement",
        model=model,
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)),
        input_schema=Draft,
        output_schema=Review,
        instruction=(
            "You fact-check release announcements. The only facts are these changelog "
            "entries:\n{changelog}\n\nList every sentence of the draft that states a fact, "
            "benefit or number that no entry supports. Approve only if the list is empty."
        ),
    )

    def read_changelog(node_input: str):
        """Function node. version_in_facts=False reproduces the reviewer's false rejection."""
        return parse_changelog(node_input, version_in_facts)

    return Workflow(
        name="announce_release",
        edges=[
            ("START", read_changelog, writer, reviewer, gate),
            (gate, {"approve": publish, "reject": send_back}),
        ],
    )
