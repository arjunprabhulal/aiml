"""The docs assistant checks several manual pages at once against a slow docs host.

ADK starts every function call from one model response together. Whether they overlap
depends on the tool: an async tool that awaits its I/O does; a blocking one holds the event loop.
"""
import argparse
import asyncio
import os
import sys

import httpx
from google.adk import Agent, Runner
from google.adk.agents.run_config import RunConfig, ToolThreadPoolConfig
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
DOCS_URL = os.environ.get("DOCS_URL", "http://127.0.0.1:8770")


def summary(page: str, response: httpx.Response) -> dict:
    if response.status_code != 200:
        return {"page": page, "ok": False, "status": response.status_code}
    text = response.json()["text"]
    return {"page": page, "ok": True, "title": text.splitlines()[0].lstrip("# "), "words": len(text.split())}


async def fetch_page(page: str) -> dict:
    """Fetch one page of the docuctl manual, such as rollback or hooks, and report whether it is reachable.
    Call this once per page; several calls can run at the same time."""
    async with httpx.AsyncClient(timeout=10) as client:
        return summary(page, await client.get(f"{DOCS_URL}/pages/{page}"))  # await: the loop runs other calls


def fetch_page_blocking(page: str) -> dict:
    """Fetch one page of the docuctl manual, such as rollback or hooks, and report whether it is reachable."""
    return summary(page, httpx.get(f"{DOCS_URL}/pages/{page}", timeout=10))  # blocks its thread


async def fetch_page_async_but_blocking(page: str) -> dict:
    """Fetch one page of the docuctl manual, such as rollback or hooks, and report whether it is reachable."""
    return summary(page, httpx.get(f"{DOCS_URL}/pages/{page}", timeout=10))  # async def, but nothing is awaited


INSTRUCTION = """You check the docuctl manual for broken pages.
When asked about several pages, call fetch_page once for each page, all in the same response.
Then list each page as reachable or not, with its title. Keep answers under 80 words."""


def make_agent(tool=fetch_page) -> Agent:
    instruction = INSTRUCTION.replace("fetch_page", tool.__name__)
    return Agent(
        name="docs_assistant",
        model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
        instruction=instruction,
        tools=[tool],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
    )


# Sync tools run on worker threads instead of the event loop. Async tools are not affected.
THREAD_POOL = RunConfig(tool_thread_pool_config=ToolThreadPoolConfig(max_workers=4))


async def ask(agent: Agent, text: str, run_config: RunConfig | None = None) -> list:
    runner = Runner(app_name="docs", agent=agent, session_service=InMemorySessionService(),
                    auto_create_session=True)
    message = types.Content(role="user", parts=[types.Part(text=text)])
    events = [e async for e in runner.run_async(user_id="dana", session_id="s1", new_message=message,
                                                run_config=run_config or RunConfig())]
    await runner.close()
    return events


def parse_options(argv=None):
    parser = argparse.ArgumentParser(description="Check manual pages using a chosen tool and optional sync-tool worker pool.")
    parser.add_argument("question", help="question to send to the configured model")
    parser.add_argument("--tool", choices=["async", "sync", "blocking-async"], default="async")
    parser.add_argument("--workers", type=int, help="max_workers for sync tools; not an overall request limit")
    args = parser.parse_args(argv)
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be at least 1")
    return args


def selected_run(args):
    tool = {"async": fetch_page, "sync": fetch_page_blocking,
            "blocking-async": fetch_page_async_but_blocking}[args.tool]
    config = RunConfig(tool_thread_pool_config=ToolThreadPoolConfig(max_workers=args.workers)) if args.workers else RunConfig()
    return make_agent(tool), config


async def main(question: str, agent=None, run_config=None) -> None:
    for event in await ask(agent or make_agent(), question, run_config):
        for call in event.get_function_calls():
            print("call  ", call.name, call.args)
        if event.is_final_response() and event.content:
            print("answer", "".join(p.text or "" for p in event.content.parts if not p.thought))


if __name__ == "__main__":
    options = parse_options()
    agent, config = selected_run(options)
    asyncio.run(main(options.question, agent, config))
