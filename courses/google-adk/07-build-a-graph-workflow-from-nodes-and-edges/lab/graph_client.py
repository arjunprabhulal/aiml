"""Run one supplied log through the original Workflow; no recorder or .env autoload."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from google.adk.runners import InMemoryRunner
from release_notes import build_workflow
from harness import run

HERE = Path(__file__).parent

def parse_options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "sample-log.txt", help="one existing UTF-8 log file")
    return parser.parse_args(argv)

async def run_one(options, model=None):
    text = options.input.read_text(encoding="utf-8")
    if not text.strip(): raise ValueError("input log must contain text")
    workflow = build_workflow(model=model or os.environ.get("DOCS_MODEL") or None)
    runner = InMemoryRunner(agent=workflow, app_name="docs_assistant")
    try:
        events, session_id = await run(workflow, text, runner=runner)
        result = {"session_id": session_id, "input_file": str(options.input), "events": events}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    finally:
        await runner.close()

if __name__ == "__main__":
    asyncio.run(run_one(parse_options()))
