"""Run the docs assistant with a tuned RunConfig and show when the runner commits state.

Run from this folder with GOOGLE_API_KEY set: python tune.py
Set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally through LiteLlm.
"""
import asyncio
import os
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.agents import RunConfig
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
DOCS = Path(__file__).resolve().parent / "docs"
APP, USER = "docs_assistant", "dev-1"
LOG: list[str] = []  # what the tool and the model callback saw, in order


async def read_page(page: str, tool_context: ToolContext) -> dict:
    """Read one page of the docuctl documentation.

    Args:
        page: The page name: config, deploy, rollback or tokens.
    """
    if page not in {"config", "deploy", "rollback", "tokens"}:
        return {"error": f"No page {page!r}."}
    tool_context.state["last_page"] = page  # recorded in this event's state_delta, not yet in the store
    service = tool_context.get_invocation_context().session_service
    stored = await service.get_session(app_name=APP, user_id=USER, session_id=tool_context.session.id)
    LOG.append(f"  tool   request_id={tool_context.custom_metadata.get('request_id')} "
               f"state[last_page]={tool_context.state.get('last_page')!r} "
               f"stored[last_page]={stored.state.get('last_page')!r}")
    path = DOCS / f"{page}.md"
    return {"page": page, "text": path.read_text(encoding="utf-8")} if path.is_file() else {"error": f"No page {page!r}."}


def count_history(callback_context, llm_request) -> None:
    """Log how many contents each model call receives; returning None lets the call run."""
    LOG.append(f"  model  call with {len(llm_request.contents)} contents")


root_agent = Agent(
    name=APP,
    model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
    instruction="""You answer questions from developers about docuctl, the team's deploy CLI.
Read the relevant page with read_page before you answer, and answer only from it.
Keep the answer under 40 words.""",
    tools=[read_page],
    before_model_callback=count_history,
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
)


def run_config(request_id: str, recent_events: int | None = None, timeout_ms: int = 60_000) -> RunConfig:
    return RunConfig(
        max_llm_calls=4,  # one question needs two calls: the tool call and the answer
        custom_metadata={"request_id": request_id},  # copied onto every event of this invocation
        get_session_config=GetSessionConfig(num_recent_events=recent_events) if recent_events else None,
        http_options=types.HttpOptions(timeout=timeout_ms, retry_options=types.HttpRetryOptions(attempts=3)),
    )


async def ask(runner: Runner, session_id: str, text: str, config: RunConfig) -> list:
    """Run one turn; after each event, log its state delta and what the session service holds."""
    message = types.Content(role="user", parts=[types.Part(text=text)])
    events = []
    async for event in runner.run_async(user_id=USER, session_id=session_id, new_message=message, run_config=config):
        events.append(event)
        stored = await runner.session_service.get_session(app_name=APP, user_id=USER, session_id=session_id)
        kind = ("error" if event.error_code else "call" if event.get_function_calls()
                else "result" if event.get_function_responses() else "answer")
        LOG.append(f"  event {kind:<6} state_delta={dict(event.actions.state_delta)} "
                   f"stored[last_page]={stored.state.get('last_page')!r} metadata={event.custom_metadata}"
                   + (f" error_code={event.error_code}" if event.error_code else ""))
    return events


async def main() -> None:
    runner = Runner(app_name=APP, agent=root_agent, session_service=InMemorySessionService())
    session = await runner.session_service.create_session(app_name=APP, user_id=USER)
    turns = [("req-1", "How do I roll back production?", None),
             ("req-2", "Which page covers CI tokens?", None),
             ("req-3", "What was my first question?", 4)]
    try:
        for request_id, text, recent in turns:
            LOG.append(f"{request_id}: {text}" + (f"  (num_recent_events={recent})" if recent else ""))
            events = await ask(runner, session.id, text, run_config(request_id, recent))
            LOG.append(f"  answer: {events[-1].content.parts[-1].text}")
    finally:
        await runner.close()
    print("\n".join(LOG))


if __name__ == "__main__":
    asyncio.run(main())
