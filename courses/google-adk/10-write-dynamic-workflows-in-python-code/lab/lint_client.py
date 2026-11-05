"""Choose bundled docs pages and inspect proposed changes without rewriting the files."""
import argparse
import asyncio
import json
import os
from google.adk.runners import InMemoryRunner
from lint_changed import DOCS, build_workflow
from harness import run

def parse_options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pages", nargs="*", default=["quickstart.md", "install.md", "cli.md"])
    args = parser.parse_args(argv)
    if not args.pages: parser.error("choose at least one page")
    for name in args.pages:
        page = (DOCS / name).resolve()
        if any(char.isspace() for char in name) or not name.endswith(".md") or not page.is_relative_to(DOCS.resolve()) or not page.is_file():
            parser.error("choose an existing Markdown page inside this lab's docs folder")
    return args

async def run_one(options, model=None):
    workflow = build_workflow(model=model or os.environ.get("DOCS_MODEL") or None)
    runner = InMemoryRunner(agent=workflow, app_name="docs_assistant")
    try:
        events, session_id = await run(workflow, " ".join(options.pages), runner=runner)
        result = {"session_id": session_id, "pages": options.pages, "events": events}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    finally:
        await runner.close()

if __name__ == "__main__": asyncio.run(run_one(parse_options()))
