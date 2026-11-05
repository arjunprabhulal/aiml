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
from refine_entry import build_workflow, MAX_ROUNDS

async def compare(*, live=False):
    record = json.loads((HERE / "refine-run.json").read_text())
    for filename in ("change-rename.txt", "change-config.txt"):
        saved = next(r for r in record["runs"] if r["change"] == filename and r["reviser_sees_rules"])
        model = None if live else replay(saved, record)
        rows = await invoke(build_workflow(model), (HERE / filename).read_text(),
                            max_llm_calls=1 + MAX_ROUNDS)
        display(filename, rows)

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
    messages = [row["message"] for row in rows if row.get("message")]
    if messages:
        print(messages[-1])


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
