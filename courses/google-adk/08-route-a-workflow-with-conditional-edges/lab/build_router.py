"""Route a docs-site build log: broken links go to a triage agent, a clean build ends early."""
import re
from pathlib import Path

from google.adk import Agent, Event, Workflow
from google.genai import types
from google.adk.workflow import DEFAULT_ROUTE
from pydantic import BaseModel

BROKEN = re.compile(r"^WARNING broken link in (\S+): (\S+) \((.+)\)$")
PAGES = Path(__file__).with_name("docs-pages.txt").read_text().split()


class BrokenLink(BaseModel):
    page: str
    target: str
    reason: str


class BrokenLinks(BaseModel):
    links: list[BrokenLink]


class LinkFix(BaseModel):
    page: str
    target: str
    replacement: str


class LinkFixes(BaseModel):
    fixes: list[LinkFix]


def classify_build(node_input: str):
    """Router node: parse the log and pick the next edge. No model call."""
    lines = node_input.strip().splitlines()
    links = [BrokenLink(page=m[1], target=m[2], reason=m[3])
             for m in map(BROKEN.match, lines) if m]
    if not lines or lines[-1] != "INFO    Build finished":
        return Event(route="incomplete", output=BrokenLinks(links=links))
    if links:
        return Event(route="broken_links", output=BrokenLinks(links=links),
                     state={"pages": PAGES})
    return Event(route="clean", output=BrokenLinks(links=[]))


def report_clean(node_input: BrokenLinks):
    return Event(message="Build passed: no broken links.")


def ask_for_rerun(node_input: BrokenLinks):
    return Event(message="The build log has no 'Build finished' line. Rerun the build before triage.")


def check_fixes(node_input: LinkFixes, pages: list[str]):
    """Keep only replacements that name a page that exists; flag the rest for a person."""
    lines = []
    for fix in node_input.fixes:
        page = fix.replacement.split("#", 1)[0]
        verdict = "ok" if page in pages else "needs a person: page does not exist"
        lines.append(f"- {fix.page}: {fix.target} -> {fix.replacement} ({verdict})")
    return Event(message="Suggested link fixes:\n" + "\n".join(lines))


def build_workflow(model=None) -> Workflow:
    triage = Agent(
        name="triage_links",
        model=model or "gemini-3.8-flash",  # or LiteLlm(model="ollama_chat/gemma4:e2b")
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)),
        input_schema=BrokenLinks,
        output_schema=LinkFixes,
        instruction=(
            "For each broken link, suggest a replacement target. Use only these pages: "
            "{pages}. For a missing anchor, keep the page and suggest the closest anchor."
        ),
    )
    return Workflow(
        name="build_router",
        edges=[
            ("START", classify_build),
            (classify_build, {
                "broken_links": triage,
                "clean": report_clean,
                DEFAULT_ROUTE: ask_for_rerun,
            }),
            (triage, check_fixes),
        ],
    )
