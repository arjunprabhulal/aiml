"""Review one selected diff through the original isolated collaborative team."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from google.adk.runners import InMemoryRunner
from review_team import build_team, delegations
from harness import run

HERE = Path(__file__).parent

def parse_options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", type=Path, default=HERE / "docs-pr.diff")
    return parser.parse_args(argv)

async def run_one(options, model=None):
    diff = options.diff.read_text(encoding="utf-8")
    if not diff.strip(): raise ValueError("diff must contain text")
    team = build_team(model=model or os.environ.get("DOCS_MODEL") or None)
    runner = InMemoryRunner(agent=team, app_name="docs_assistant")
    try:
        events, session_id = await run(team, f"Review this docs pull request:\n\n{diff}", runner=runner)
        result = {"session_id": session_id, "delegations": delegations(events), "events": events}
        print(json.dumps(result, ensure_ascii=False, indent=2)); return result
    finally:
        await runner.close()

if __name__ == "__main__": asyncio.run(run_one(parse_options()))
