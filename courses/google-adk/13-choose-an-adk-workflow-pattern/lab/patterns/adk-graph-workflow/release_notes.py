"""Turn `git log --oneline` output into grouped release notes with an ADK graph workflow."""
import re

from google.adk import Agent, Event, Workflow
from google.genai import types
from pydantic import BaseModel

LINE = re.compile(r"^([0-9a-f]{7,40}) (.+)$")


class Commits(BaseModel):
    subjects: list[str]


class ReleaseGroups(BaseModel):
    features: list[str]
    fixes: list[str]
    docs: list[str]


def parse_log(node_input: str):
    """Function node: keep each commit subject, refuse anything that is not a log line."""
    subjects = []
    for line in node_input.strip().splitlines():
        match = LINE.match(line.strip())
        if not match:
            raise ValueError(f"not a git log --oneline line: {line!r}")
        subjects.append(match[2])
    return Event(output=Commits(subjects=subjects), state={"subjects": subjects})


def render_notes(node_input: ReleaseGroups, subjects: list[str]):
    """Function node: check that every commit is listed once, then write Markdown."""
    grouped = node_input.features + node_input.fixes + node_input.docs
    if sorted(grouped) != sorted(subjects):
        missing = sorted(set(subjects) - set(grouped))
        extra = sorted(set(grouped) - set(subjects))
        raise ValueError(f"groups do not match the log: missing={missing} extra={extra}")
    sections = [("Features", node_input.features), ("Fixes", node_input.fixes),
                ("Documentation", node_input.docs)]
    body = "\n\n".join(f"## {title}\n" + "\n".join(f"- {item}" for item in items)
                       for title, items in sections if items)
    return Event(message=f"# Release notes\n\n{body}")


def build_workflow(model=None, thinking_level=types.ThinkingLevel.LOW) -> Workflow:
    config = types.GenerateContentConfig(max_output_tokens=1024)
    if thinking_level:  # e.g. "low": less hidden reasoning for a simple sorting task
        config = types.GenerateContentConfig(
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_level=thinking_level))
    group_changes = Agent(
        name="group_changes",
        model=model or "gemini-3.8-flash",  # or LiteLlm(model="ollama_chat/gemma4:e2b")
        generate_content_config=config,
        input_schema=Commits,
        output_schema=ReleaseGroups,
        instruction=(
            "Sort every commit subject into exactly one list: features (new behavior), "
            "fixes (a bug or crash fixed) or docs (documentation pages only). "
            "Copy each subject exactly as written."
        ),
    )
    return Workflow(
        name="release_notes",
        edges=[("START", parse_log, group_changes, render_notes)],
    )
