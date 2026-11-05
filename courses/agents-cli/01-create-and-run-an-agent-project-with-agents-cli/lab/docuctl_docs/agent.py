"""The docuctl docs assistant scaffolded with Google Agents CLI 1.11.0."""

from __future__ import annotations

import os
import re
from pathlib import Path

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

DOCS = Path(__file__).resolve().parent / "docs"
PAGES = sorted(p.stem for p in DOCS.glob("*.md"))
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
MAX_PROJECT_NAME_LENGTH = 26
PROJECT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")

INSTRUCTION = """You answer questions from developers about docuctl, the team's deploy CLI.
Read the relevant page with read_page before you answer. Answers depend on the developer's
docuctl major version (1.x or 2.x). State the exact command and keep the answer under 80 words."""


def read_page(page: str) -> dict[str, str]:
    """Read one page of the docuctl documentation: config, deploy, rollback or tokens."""
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    return {"page": page, "text": (DOCS / f"{page}.md").read_text(encoding="utf-8")}


def validate_project_name(project_name: str) -> str:
    """Apply the agents-cli scaffold create project-name rules (<=26 chars, lowercase/digits/hyphens)."""
    if len(project_name) > MAX_PROJECT_NAME_LENGTH:
        raise ValueError(
            f"Project name '{project_name}' exceeds {MAX_PROJECT_NAME_LENGTH} characters. "
            "Please use a shorter name."
        )
    if not PROJECT_NAME_RE.match(project_name):
        raise ValueError(
            f"Project name '{project_name}' must start with a lowercase letter and contain only "
            "lowercase letters, digits, and hyphens."
        )
    return project_name


def validate_manifest_contract(app_name: str, agent_directory: str) -> dict[str, str]:
    """Verify that App(name=...) matches agent_directory in agents-cli-manifest.yaml."""
    if app_name != agent_directory:
        raise ValueError(
            f"App(name={app_name!r}) does not match manifest agent_directory={agent_directory!r}: "
            f"ADK mounts /apps/{agent_directory}/... while A2A mounts /a2a/{app_name}."
        )
    return {
        "adk_session_route": f"/apps/{agent_directory}/users/cli-user/sessions",
        "a2a_card_route": f"/a2a/{app_name}/.well-known/agent-card.json",
    }



root_agent = Agent(
    name="docuctl_docs",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=1),
    ),
    instruction=INSTRUCTION,
    tools=[read_page],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=1024,
        thinking_config=types.ThinkingConfig(thinking_level="low"),
    ),
)
app = App(root_agent=root_agent, name="app")
