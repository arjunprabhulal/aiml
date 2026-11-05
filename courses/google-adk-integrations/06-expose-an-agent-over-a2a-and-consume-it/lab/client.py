"""A release coordinator that delegates docs questions to the remote docs assistant over A2A.

Run (with server.py running): python client.py "How do I roll back production to r41?"
"""
import asyncio
import os
import sys

import httpx
from google.adk import Agent, Runner
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH, RemoteA2aAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.genai import types

MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
DOCS_URL = os.environ.get("DOCS_A2A_URL", "http://localhost:8001")


def remote_docs(url: str = DOCS_URL, timeout: float = 60.0, httpx_client: httpx.AsyncClient | None = None):
    """The remote agent, described by the card it serves at the well-known path."""
    return RemoteA2aAgent(
        name="docs_assistant",
        description="Answers questions about the docuctl documentation.",
        agent_card=f"{url}{AGENT_CARD_WELL_KNOWN_PATH}",
        timeout=timeout,
        httpx_client=httpx_client,
    )


def build_agent(model=None, remote: RemoteA2aAgent | None = None) -> Agent:
    return Agent(
        name="release_coordinator",
        model=model or (LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL),
        instruction="You coordinate docuctl releases. Transfer every question about how docuctl works "
                    "to docs_assistant. Answer release scheduling questions yourself.",
        sub_agents=[remote or remote_docs()],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
    )


async def ask(text: str, agent: Agent | None = None) -> list:
    sessions = InMemorySessionService()
    runner = Runner(app_name="releases", agent=agent or build_agent(), session_service=sessions)
    try:
        session = await sessions.create_session(app_name="releases", user_id="dev")
        message = types.Content(role="user", parts=[types.Part(text=text)])
        return [e async for e in runner.run_async(user_id="dev", session_id=session.id, new_message=message)]
    finally:
        await runner.close()


def show(events: list) -> str:
    lines = []
    for event in events:
        for call in event.get_function_calls():
            lines.append(f"{event.author}: call {call.name} {call.args}")
        if event.error_code or event.error_message:
            lines.append(f"{event.author}: error {event.error_code} {event.error_message}")
        text = "".join(p.text or "" for p in (event.content.parts if event.content else None) or [] if not p.thought)
        if text.strip():
            lines.append(f"{event.author}: {text.strip()}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(show(asyncio.run(ask(" ".join(sys.argv[1:])))))
