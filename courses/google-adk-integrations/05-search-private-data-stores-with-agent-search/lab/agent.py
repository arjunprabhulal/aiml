"""The docs assistant answers from the team's private engineering docs through Agent Search."""
import asyncio
import os
import sys

from google.adk import Agent, Runner
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.sessions import InMemorySessionService
from google.adk.tools import VertexAiSearchTool
from google.genai import types

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
# VertexAiSearchTool is a Gemini built-in tool, so the model must run on Agent Platform, not the Gemini API.
os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "true")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")  # gemini-3.8-flash is served from the global endpoint
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
STORE_ID = os.environ.get("DOCS_SEARCH_STORE", "aiml-lesson-agent-search")
STORE = f"projects/{PROJECT}/locations/global/collections/default_collection/dataStores/{STORE_ID}"


class TeamSearch(VertexAiSearchTool):
    """Build a filter from a validated application-supplied team; this demo has no login."""

    def __init__(self, **kwargs):
        if kwargs.get("bypass_multi_tools_limit"):
            raise ValueError("TeamSearch requires its dynamic team filter; bypass mode discards it")
        super().__init__(**kwargs)

    def _build_vertex_ai_search_config(self, readonly_context: ReadonlyContext) -> types.VertexAISearch:
        team = readonly_context.state.get("team")
        if not isinstance(team, str) or team not in {"docs", "platform"}:
            raise ValueError("Search requires a known team from application state")
        config = super()._build_vertex_ai_search_config(readonly_context)
        config.filter = f'team: ANY("{team}")'
        return config


def build_agent(model=None, search: VertexAiSearchTool | None = None) -> Agent:
    return Agent(
        name="private_docs",
        model=model or MODEL,
        instruction="""You answer engineers' questions from the team's private engineering documents:
decision records, runbooks, postmortems and style guides. Answer only from what the search returns,
and name the document you used. If the search returns nothing relevant, say you found no document.""",
        tools=[search or TeamSearch(data_store_id=STORE, max_results=3)],
        generate_content_config=types.GenerateContentConfig(temperature=0.2),
    )


async def ask(text: str, agent: Agent | None = None, team: str | None = None) -> list:
    sessions = InMemorySessionService()
    runner = Runner(app_name="docs", agent=agent or build_agent(), session_service=sessions)
    try:
        session = await sessions.create_session(app_name="docs", user_id="dev", state={"team": team} if team else None)
        message = types.Content(role="user", parts=[types.Part(text=text)])
        return [e async for e in runner.run_async(user_id="dev", session_id=session.id, new_message=message)]
    finally:
        await runner.close()


def sources(event) -> list[str]:
    """The documents Agent Search returned for this answer, from the grounding metadata."""
    chunks = (event.grounding_metadata.grounding_chunks or []) if event.grounding_metadata else []
    return [c.retrieved_context.title or c.retrieved_context.uri for c in chunks if c.retrieved_context]


def show(events: list) -> str:
    lines = []
    for event in events:
        if event.grounding_metadata:
            queries = event.grounding_metadata.retrieval_queries or []
            lines.append(f"search {queries} -> {sources(event)}")
        if event.is_final_response() and event.author != "user" and event.content:
            lines.append("answer " + "".join(p.text or "" for p in event.content.parts if not p.thought).strip())
    return "\n".join(lines)


if __name__ == "__main__":
    team = os.environ.get("DOCS_TEAM")
    print(show(asyncio.run(ask(" ".join(sys.argv[1:]), team=team))))
