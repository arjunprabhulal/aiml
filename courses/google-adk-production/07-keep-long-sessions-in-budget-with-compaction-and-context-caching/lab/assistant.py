"""The docs assistant with the docuctl manual in a cached prefix and old turns compacted.

The manual goes in static_instruction, so every request starts with the same few thousand tokens
that ContextCacheConfig can cache. Deploy logs come back as large tool results, and
EventsCompactionConfig replaces old turns with a model-written summary.
"""
import asyncio
import os
import sys
from pathlib import Path

from google.adk import Agent, Runner
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.genai import types

HERE = Path(__file__).resolve().parent
# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
# Context caching is a Gemini feature: on Gemma, ContextCacheConfig has no effect.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
MANUAL = "\n\n".join(p.read_text(encoding="utf-8") for p in sorted((HERE / "docs").glob("*.md")))
RELEASES = sorted(p.stem for p in (HERE / "logs").glob("*.log"))

STATIC = f"""You answer questions from developers about docuctl, the team's deploy CLI.
Answer only from the docuctl manual below and from deploy logs you read with read_deploy_log.
Name the exact command when one exists. If the manual does not cover a question, say so.

<manual>
{MANUAL}
</manual>"""


def read_deploy_log(release: str) -> dict:
    """Read the full staging deploy log of one release, such as r42."""
    if release not in RELEASES:
        return {"error": f"No log for {release!r}. Releases: {', '.join(RELEASES)}."}
    return {"release": release, "log": (HERE / "logs" / f"{release}.log").read_text(encoding="utf-8")}


def model():
    return LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL


root_agent = Agent(
    name="docs_assistant",
    model=model(),
    static_instruction=STATIC,  # sent as the system instruction, identical on every request
    instruction="Keep each answer under 80 words.",  # dynamic part: sent after the cached prefix
    tools=[read_deploy_log],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
)

CACHE = ContextCacheConfig(
    min_tokens=4096,     # skip caching below this many prompt tokens
    ttl_seconds=600,     # each cache lives 10 minutes
    cache_intervals=10,  # and serves at most 10 invocations before it is rebuilt
)


def compaction(summarizer_llm=None) -> EventsCompactionConfig:
    """Summarize every 2 new invocations, overlapping the previous window by 1."""
    summarizer = LlmEventSummarizer(llm=summarizer_llm) if summarizer_llm else None
    return EventsCompactionConfig(compaction_interval=2, overlap_size=1, summarizer=summarizer)


def make_app(agent: Agent = root_agent, cache: bool = True, compact: bool = True,
             summarizer_llm=None) -> App:
    return App(
        name="docs",
        root_agent=agent,
        context_cache_config=CACHE if cache else None,
        events_compaction_config=compaction(summarizer_llm) if compact else None,
    )


def make_runner(app: App) -> Runner:
    return Runner(app=app, session_service=InMemorySessionService())


async def ask(runner: Runner, session_id: str, text: str) -> list:
    message = types.Content(role="user", parts=[types.Part(text=text)])
    return [e async for e in runner.run_async(user_id="dana", session_id=session_id, new_message=message)]


def usage(event) -> dict | None:
    """Token counts and cache state of the model call behind one event."""
    u, c = event.usage_metadata, event.cache_metadata
    if u is None:
        return None
    return {"prompt": u.prompt_token_count, "cached": u.cached_content_token_count or 0,
            "cache": None if c is None else ("active" if c.cache_name else "fingerprint only"),
            "cache_uses": None if c is None else c.invocations_used}


async def main(question: str) -> None:
    runner = make_runner(make_app())
    session = await runner.session_service.create_session(app_name="docs", user_id="dana")
    for event in await ask(runner, session.id, question):
        print(event.author, usage(event), [p.text for p in (event.content.parts if event.content else []) if p.text])
    await runner.close()


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:])))
