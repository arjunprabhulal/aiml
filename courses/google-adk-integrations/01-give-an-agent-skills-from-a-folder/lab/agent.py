"""The docs assistant with skills loaded from a folder through SkillToolset."""
import asyncio
import os
import sys
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.code_executors import UnsafeLocalCodeExecutor
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.adk.skills import load_skills_from_dir
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import types

HERE = Path(__file__).resolve().parent
# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
PAGES = sorted(p.stem for p in (HERE / "docs").glob("*.md"))
MERGED = {  # the merged pull requests per version, as a release tool would return them
    "2.4.0": [
        {"number": 212, "title": "feat: add --dry-run to rollback"},
        {"number": 215, "title": "fix: keep the token cache after a failed login"},
        {"number": 218, "title": "feat!: remove the deprecated release revert command"},
        {"number": 220, "title": "docs: document rollback --to"},
        {"number": 221, "title": "ci: cache the Go toolchain"},
    ],
}


def read_page(page: str) -> dict:
    """Read one page of the docuctl documentation: config, deploy, rollback or tokens."""
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    root = (HERE / "docs").resolve()
    path = (root / f"{page}.md").resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return {"error": f"No readable docs page {page!r}."}
    return {"page": page, "text": path.read_text(encoding="utf-8")}


def list_merged_prs(version: str) -> dict:
    """List the pull requests merged into a docuctl version, such as 2.4.0."""
    if version not in MERGED:
        return {"error": f"No release {version!r}. Known: {', '.join(MERGED)}."}
    return {"version": version, "pull_requests": MERGED[version]}


def skills_toolset(folder: Path = HERE / "skills", run_scripts: bool = True) -> SkillToolset:
    """Every skill folder under skills/; list_merged_prs is offered only after release-notes is loaded."""
    return SkillToolset(
        skills=load_skills_from_dir(folder),
        # Runs skill scripts in a child Python process with your permissions: local development only.
        code_executor=UnsafeLocalCodeExecutor() if run_scripts else None,
        script_timeout=30,
        additional_tools=[list_merged_prs],
    )


def build_agent(model=None, toolset: SkillToolset | None = None) -> Agent:
    return Agent(
        name="docs_assistant",
        model=model or (LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL),
        instruction="You help developers keep the docuctl documentation and releases correct. "
                    "Read pages with read_page. Say plainly when you cannot do something with your tools.",
        tools=[read_page, toolset or skills_toolset()],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
    )


async def ask(text: str, agent: Agent | None = None) -> list:
    sessions = InMemorySessionService()
    runner = Runner(app_name="docs", agent=agent or build_agent(), session_service=sessions)
    try:
        session = await sessions.create_session(app_name="docs", user_id="dev")
        message = types.Content(role="user", parts=[types.Part(text=text)])
        return [e async for e in runner.run_async(user_id="dev", session_id=session.id, new_message=message)]
    finally:
        await runner.close()


def show(events: list, width: int = 160) -> str:
    lines = []
    for event in events:
        for call in event.get_function_calls():
            lines.append(f"call   {call.name} {call.args}")
        for result in event.get_function_responses():
            lines.append(f"result {result.name} {str(result.response)[:width]}")
        if event.is_final_response() and event.author != "user" and event.content:
            lines.append("answer " + "".join(p.text or "" for p in event.content.parts if not p.thought).strip())
    return "\n".join(lines)


if __name__ == "__main__":
    print(show(asyncio.run(ask(" ".join(sys.argv[1:])))))
