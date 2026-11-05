"""Expose the docs assistant as an A2A server with to_a2a, served by uvicorn.

Run: python server.py            # serves http://localhost:8001 and /.well-known/agent-card.json
"""
import contextlib
import os
import socket
import threading
import time
from pathlib import Path

import uvicorn
from google.adk import Agent
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

HERE = Path(__file__).resolve().parent
# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
PAGES = sorted(p.stem for p in (HERE / "docs").glob("*.md"))


def read_page(page: str) -> dict:
    """Read one page of the docuctl documentation: config, deploy, rollback or tokens."""
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    root = (HERE / "docs").resolve()
    path = (root / f"{page}.md").resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return {"error": f"No readable docs page {page!r}."}
    return {"page": page, "text": path.read_text(encoding="utf-8")}


def build_agent(model=None) -> Agent:
    return Agent(
        name="docs_assistant",
        description="Answers questions about the docuctl documentation: config, deploy, rollback and tokens.",
        model=model or (LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL),
        instruction="Answer from the docuctl documentation only. Read the page with read_page and name it. "
                    "If the docs do not cover the question, say so.",
        tools=[read_page],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
    )


def build_app(agent: Agent | None = None, port: int = 8001, card_port: int | None = None):
    """The Starlette app. The agent card advertises http://localhost:{card_port or port}/ as the RPC URL."""
    return to_a2a(agent or build_agent(), host="localhost", port=card_port or port)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextlib.contextmanager
def running(app, port: int, startup_timeout: float = 10.0):
    """Serve app with uvicorn in a background thread, for the recorder and the tests."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + startup_timeout
        while not server.started:
            if not thread.is_alive():
                raise RuntimeError("A2A server failed to start; check its log and port")
            if time.monotonic() >= deadline:
                raise TimeoutError("A2A server startup timed out")
            time.sleep(0.05)
        yield f"http://localhost:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8001)
