"""Run the docs assistant against simulated docs-service failures with ADK environment simulation.

The tools stay unchanged. EnvironmentSimulationFactory.create_plugin() intercepts their calls
and returns an injected error or response instead of running them.
"""
import os
from pathlib import Path

from google.adk import Agent
from google.adk.apps import App
from google.adk.models.lite_llm import LiteLlm
from google.adk.plugins.reflect_retry_tool_plugin import ReflectAndRetryToolPlugin
from google.adk.runners import InMemoryRunner
from google.adk.tools.environment_simulation import EnvironmentSimulationFactory
from google.adk.tools.environment_simulation.environment_simulation_config import (
    EnvironmentSimulationConfig, InjectedError, InjectionConfig, ToolSimulationConfig)
from google.genai import types

MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")  # or ollama_chat/gemma4:e2b
DOCS = Path(__file__).resolve().parent / "docs"
INSTRUCTION = ("Answer questions about the docs-assistant project from its docs only. Call list_pages, "
               "then read_page on the one page that answers. Reply in one sentence and end it with the "
               "page path in parentheses.")
# Tell the agent what each error result means; without it the model guesses.
ON_ERROR = (" A read_page result with error_code 404 means that page does not exist: try another page from "
            "list_pages. Any other error_code means the docs service failed: say so and do not answer from "
            "memory. Never cite a page you could not read.")


def list_pages() -> dict:
    """List the docs pages by path."""
    return {"pages": sorted(page.name for page in DOCS.glob("*.md"))}


def read_page(path: str) -> dict:
    """Return the Markdown of one docs page from the docs service, by the path list_pages returned."""
    page = DOCS / path
    if page.parent != DOCS or not page.is_file():
        return {"error": f"No page {path!r}. Call list_pages for valid paths."}
    return {"path": path, "content": page.read_text(encoding="utf-8")}


def fail(code: int, message: str, **options) -> InjectionConfig:
    return InjectionConfig(injected_error=InjectedError(injected_http_error_code=code, error_message=message), **options)


FAULTS = {
    "outage": [fail(503, "Docs service unavailable.")],
    "missing-page": [fail(404, "Page not found.", match_args={"path": "install.md"})],
    "flaky": [fail(503, "Docs service unavailable.", injection_probability=0.5, random_seed=1)],
}


class RetryOnErrorCode(ReflectAndRetryToolPlugin):
    """ReflectAndRetryToolPlugin reacts to exceptions; injected faults are results with error_code."""

    async def extract_error_from_result(self, *, tool, tool_args, tool_context, result):
        return result if isinstance(result, dict) and "error_code" in result else None


def build_app(fault: str | None = None, instruction: str = INSTRUCTION, retry: str | None = None) -> App:
    """fault: a FAULTS key. retry: None, "raise" (the plugin's default) or "answer"."""
    agent = Agent(
        name="docs_assistant",
        model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
        instruction=instruction,
        tools=[list_pages, read_page],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
    )
    plugins = []
    if fault:
        config = EnvironmentSimulationConfig(tool_simulation_configs=[
            ToolSimulationConfig(tool_name="read_page", injection_configs=FAULTS[fault])])
        plugins.append(EnvironmentSimulationFactory.create_plugin(config))
    if retry:
        plugins.append(RetryOnErrorCode(max_retries=2, throw_exception_if_retry_exceeded=retry == "raise"))
    return App(name="docs_assistant", root_agent=agent, plugins=plugins)


async def ask(app: App, question: str, events: list | None = None) -> list:
    """Run one question; append its events (tool calls, results, answer) to `events` as they arrive."""
    events = [] if events is None else events
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(app_name=app.name, user_id="dev")
    message = types.Content(role="user", parts=[types.Part(text=question)])
    async for event in runner.run_async(user_id="dev", session_id=session.id, new_message=message):
        events.append(event)
    return events


def show(events: list) -> list[str]:
    lines = []
    for event in events:
        for part in (event.content.parts if event.content else []):
            if part.function_call:
                lines.append(f"call   {part.function_call.name}({part.function_call.args})")
            elif part.function_response:
                body = part.function_response.response
                lines.append(f"result {part.function_response.name} -> "
                             + (str(body) if "content" not in body else f"{body['path']} ({len(body['content'])} chars)"))
            elif part.text and not part.thought:
                lines.append(f"answer {part.text.strip()}")
    return lines
