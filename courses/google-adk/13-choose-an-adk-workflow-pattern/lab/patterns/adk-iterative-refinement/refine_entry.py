"""Refine a one-line changelog entry in a graph loop until a lint passes or a round limit is hit."""

import re

from google.adk import Agent, Event, Workflow
from pydantic import BaseModel

MAX_ROUNDS = 3  # revisions after the first draft
MAX_CHARS = 80
VERBS = ("Add", "Fix", "Remove", "Rename", "Deprecate", "Change")


class Change(BaseModel):
    summary: str
    must_name: list[str]


class Entry(BaseModel):
    text: str


class Feedback(BaseModel):
    entry: str
    problems: list[str]


def load_change(node_input: str):
    """Function node: the change summary, then one identifier per 'name:' line."""
    lines = node_input.strip().splitlines()
    names = [line[5:].strip() for line in lines if line.startswith("name:")]
    summary = " ".join(line for line in lines if not line.startswith("name:"))
    return Event(output=Change(summary=summary, must_name=names),
                 state={"must_name": names, "rounds": 0})


RULES = (f"At most {MAX_CHARS} characters. Start with one of: {', '.join(VERBS)}. "
         "Put each name in must_name in backticks, exactly as written. No final period.")


def lint_entry(text: str, must_name: list[str]) -> list[str]:
    """The quality check: deterministic, so the loop's exit does not depend on a model."""
    problems = []
    if len(text) > MAX_CHARS:
        problems.append(f"{len(text)} characters; the limit is {MAX_CHARS}")
    if "\n" in text or "\r" in text:
        problems.append("write one line")
    if not re.match(r"^(?:" + "|".join(VERBS) + r") ", text):
        problems.append(f"start with one of: {', '.join(VERBS)}")
    problems += [f"name `{name}` in backticks" for name in must_name if f"`{name}`" not in text]
    if text.endswith("."):
        problems.append("drop the final period")
    return problems


def check_entry(node_input: Entry, must_name: list[str], rounds: int):
    """Router node: done, another revision, or stop at the round limit."""
    problems = lint_entry(node_input.text, must_name)
    if not problems:
        return Event(route="done", output=node_input.text)
    if rounds >= MAX_ROUNDS:
        return Event(route="limit", output=Feedback(entry=node_input.text, problems=problems))
    return Event(route="revise", output=Feedback(entry=node_input.text, problems=problems),
                 state={"rounds": rounds + 1})


def accept(node_input: str, rounds: int):
    return Event(message=f"PASSED after {rounds} revision(s): {node_input}")


def give_up(node_input: Feedback, rounds: int):
    problems = "; ".join(node_input.problems)
    return Event(message=f"STOPPED at the limit of {rounds} revisions. Last entry: "
                         f"{node_input.entry}\nStill failing: {problems}")


def build_workflow(model=None, reviser_sees_rules=True) -> Workflow:
    model = model or "gemini-3.8-flash"  # or LiteLlm(model="ollama_chat/gemma4:e2b")
    write_entry = Agent(
        name="write_entry",
        model=model,
        input_schema=Change,
        output_schema=Entry,
        # The rules live in lint_entry only; the feedback tells the model which ones it broke.
        instruction="Write one changelog line for this change. Mention every name in must_name.",
    )
    revise_entry = Agent(
        name="revise_entry",
        model=model,
        input_schema=Feedback,
        output_schema=Entry,
        # reviser_sees_rules=False reproduces the recorded oscillation: each revision
        # fixes the listed problems and breaks a rule it was never shown.
        instruction=("Rewrite the changelog line so that it fixes every listed problem. "
                     + (f"Keep every rule: {RULES} must_name: {{must_name}}"
                        if reviser_sees_rules else "")),
    )
    return Workflow(
        name="refine_entry",
        edges=[
            ("START", load_change, write_entry, check_entry),
            (check_entry, {"done": accept, "revise": revise_entry, "limit": give_up}),
            (revise_entry, check_entry),  # the back-edge that makes the loop
        ],
    )
