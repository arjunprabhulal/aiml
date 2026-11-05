"""The docs assistant reviews an uploaded ship.toml and saves its reviews as versioned artifacts.

Uploaded files and saved reviews live in an artifact store on disk (FileArtifactService),
not in the conversation history: the model sees a file only in the turn that loads it.
"""
import asyncio
import os
import sys
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.apps.app import App
from google.adk.artifacts import FileArtifactService
from google.adk.errors.input_validation_error import InputValidationError
from google.adk.models.lite_llm import LiteLlm
from google.adk.plugins.save_files_as_artifacts_plugin import SaveFilesAsArtifactsPlugin
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.adk.tools.load_artifacts_tool import LoadArtifactsTool
from google.genai import types

HERE = Path(__file__).resolve().parent
# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
STORE = Path(os.environ.get("DOCS_ARTIFACTS", HERE / "artifact-store"))
PAGES = sorted(p.stem for p in (HERE / "docs").glob("*.md"))


def read_page(page: str) -> dict:
    """Read one page of the docuctl manual, such as config, secrets, environments or upgrade-2x."""
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    return {"page": page, "text": (HERE / "docs" / f"{page}.md").read_text(encoding="utf-8")}


async def save_text_file(filename: str, text: str, tool_context: ToolContext) -> dict:
    """Save a Markdown file for the developer. Saving the same filename again creates a new version.
    Prefix the filename with user: to keep it across all of the developer's sessions."""
    part = types.Part.from_bytes(data=text.encode("utf-8"), mime_type="text/markdown")
    try:
        version = await tool_context.save_artifact(filename, part)  # records artifact_delta on the event
    except InputValidationError as error:
        return {"error": str(error)}  # the model can choose a valid name in the same turn
    return {"saved": filename, "version": version}


INSTRUCTION = """You review docuctl configuration files for developers.
When the developer uploads a file, call load_artifacts to read it, then check it against the manual
pages you read with read_page. Name each problem with the line it is on and the fix.
When the developer asks you to save something, call save_text_file with Markdown text.
Keep chat answers under 120 words."""

root_agent = Agent(
    name="docs_assistant",
    model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
    instruction=INSTRUCTION,
    tools=[read_page, save_text_file, LoadArtifactsTool()],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
)


def make_runner(agent: Agent = root_agent, store: Path = STORE) -> Runner:
    # The plugin turns each uploaded file into an artifact and leaves a placeholder in the message.
    app = App(name="docs", root_agent=agent, plugins=[SaveFilesAsArtifactsPlugin()])
    return Runner(app=app, session_service=InMemorySessionService(),
                  artifact_service=FileArtifactService(root_dir=store))


def upload(path: Path, text: str) -> types.Content:
    """A user message with a file attached, as a chat client would send it."""
    blob = types.Blob(data=path.read_bytes(), mime_type="text/plain", display_name=path.name)
    return types.Content(role="user", parts=[types.Part(text=text), types.Part(inline_data=blob)])


async def ask(runner: Runner, user_id: str, session_id: str, message: types.Content | str) -> list:
    if isinstance(message, str):
        message = types.Content(role="user", parts=[types.Part(text=message)])
    return [e async for e in runner.run_async(user_id=user_id, session_id=session_id, new_message=message)]


async def main(text: str) -> None:
    runner = make_runner()
    session = await runner.session_service.create_session(app_name="docs", user_id="dana")
    for event in await ask(runner, "dana", session.id, upload(HERE / "ship.toml", text)):
        for call in event.get_function_calls():
            print("call", call.name, call.args)
        if event.is_final_response() and event.content:
            print("".join(p.text or "" for p in event.content.parts if not p.thought))
    await runner.close()


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "Review this ship.toml before I deploy to production."))
