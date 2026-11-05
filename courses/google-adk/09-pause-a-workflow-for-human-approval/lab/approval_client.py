"""One real Workflow pause and an interactive review against a NEW local SQLite file.

The in-memory paused session stays in this process. No .env loading or recorder batch.
"""
import argparse
import asyncio
import json
import os
import sqlite3
from pathlib import Path
from google.adk.runners import InMemoryRunner
from harness import reply_to, run
from migration_gate import Decision, build_workflow, create_index
REQUEST = Path(__file__).with_name("migration-request.txt").read_text().strip()


def parse_options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", default=REQUEST)
    parser.add_argument("--reviewer", required=True, help="local review label, not authenticated identity")
    parser.add_argument("--db", type=Path, default=Path("learner-index.db"))
    args = parser.parse_args(argv)
    if not args.request.strip() or not args.reviewer.strip(): parser.error("request and reviewer need text")
    return args

async def review_payload(payload):
    print("Review this actual draft before deciding:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    while True:
        verdict = (await asyncio.to_thread(input, "Type approve or reject (Ctrl-C cancels): ")).strip()
        if verdict in ("approve", "reject"): return verdict
        print("No decision sent: type exactly approve or reject.")

async def run_one(options, model=None, review=review_payload):
    # Exclusive creation refuses any existing database BEFORE a model request or SQL change.
    with options.db.open("xb"): pass
    create_index(str(options.db.resolve()))
    workflow = build_workflow(model=model or os.environ.get("DOCS_MODEL") or None)
    runner = InMemoryRunner(agent=workflow, app_name="docs_assistant")
    try:
        paused, session_id = await run(workflow, options.request, runner=runner,
                                       state={"db_path": str(options.db.resolve())})
        print(json.dumps({"session_id": session_id, "paused_events": paused}, ensure_ascii=False, indent=2))
        calls = [c for e in paused for c in e.get("calls", []) if c["name"] == "adk_request_input"]
        resumed = []
        if calls:
            if len(calls) != 1: raise ValueError("expected one pending review")
            call = calls[0]
            verdict = await review(call["args"]["payload"])
            decision = Decision(verdict=verdict, reviewer=options.reviewer)
            resumed, _ = await run(workflow, reply_to(call["id"], decision.model_dump()),
                                   runner=runner, session_id=session_id)
        with sqlite3.connect(options.db) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(pages)")]
        result = {"resumed_events": resumed, "columns_after": columns}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    finally:
        await runner.close()

if __name__ == "__main__":
    asyncio.run(run_one(parse_options()))
