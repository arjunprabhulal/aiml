"""Compare the workflow's cases; replay saved replies unless --live is explicit."""
import argparse
import asyncio
import copy
import json
from pathlib import Path

from dotenv import load_dotenv
import os
from google.adk.agents.run_config import RunConfig
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types
from harness import ReplayLlm, summarize

HERE = Path(__file__).resolve().parent
from release_prep import build_graph, build_partial

async def compare(*, live=False):
    record = json.loads((HERE / "prep-run.json").read_text())
    for kind, filename in (("graph", "release-3.5.0.md"), ("graph", "release-3.6.0.md"),
                           ("partial", "release-3.6.0.md")):
        saved = next(r for r in record["runs"] if (r["workflow"], r["release"]) == (kind, filename))
        model = None if live else replay(saved, record)
        if live:
            builder = build_graph if kind == "graph" else build_partial
        else:
            original = __import__("importlib").import_module("release_prep")
            builder = original.build_graph if kind == "graph" else original.build_partial
        root = builder(model)
        try:
            rows = await invoke(root, (HERE / ("" if live else "") / filename).read_text(), max_llm_calls=6)
        except FileNotFoundError as error:
            print(f"\n{kind} | {filename}\n{type(error).__name__}: {error}")
        else:
            display(f"{kind} | {filename}", rows)

async def invoke(root, text, *, max_llm_calls, plugins=()):
    """Run the actual workflow and close its in-memory Runner, including on failure."""
    app = App(name="docs_assistant", root_agent=root, plugins=list(plugins))
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id="dev")
    try:
        return [summarize(event) async for event in runner.run_async(
            user_id="dev", session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
            run_config=RunConfig(max_llm_calls=max_llm_calls))]
    finally:
        await runner.close()


def replay(saved, record):
    return ReplayLlm(model=record["environment"]["model"],
                     calls=copy.deepcopy(saved["model_calls"]))


def display(label, rows):
    print(f"\n{label}")
    for row in rows:
        if row.get("route"):
            print("route:", row["route"])
    # The parent may emit a diagnostic before the assembled page.
    # Keep both so a partial page's "see the error above" has its actual cause.
    for row in rows:
        if row.get("message"):
            print(row["message"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="request new Gemini replies instead of replaying saved replies")
    args = parser.parse_args()
    if args.live:
        load_dotenv(HERE / ".env", override=False)
        if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
            parser.error("Set your Gemini API key in .env before using --live")
    print("Mode:", "live Gemini requests" if args.live else "offline replay of saved model replies")
    asyncio.run(compare(live=args.live))


if __name__ == "__main__":
    main()
