"""Run the generate-and-review workflow on two changelogs and save every event and model reply."""
import argparse
import asyncio
import json
from pathlib import Path

from harness import environment, gemini, run
from review_gate import build_workflow

HERE = Path(__file__).parent
# (changelog, writer style, does the reviewer see the version?)
RUNS = [("changelog-3.5.0.md", "upbeat", True), ("changelog-3.5.0.md", "factual", True),
        ("changelog-3.4.0.md", "factual", True), ("changelog-3.4.0.md", "factual", False)]


async def main(*, record=False):
    if not record:
        raise ValueError("Recording is opt-in: use --record in a disposable copy; existing records will be replaced.")
    runs = []
    for name, style, version_in_facts in RUNS:
        model = gemini()
        workflow = build_workflow(model, style, version_in_facts)
        events, _ = await run(workflow, (HERE / name).read_text())
        runs.append({"changelog": name, "style": style, "version_in_facts": version_in_facts,
                     "events": events, "model_calls": model.calls})
        facts = "" if version_in_facts else ", version left out of the facts"
        print(f"$ {name} with the {style} writer{facts}\n{events[-1]['message']}\n")
    record = {"environment": environment(), "runs": runs}
    (HERE / "review-run.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="Make model calls and replace the saved comparison in this copy")
    args = parser.parse_args()
    if not args.record:
        parser.error("use --record explicitly in a disposable copy")
    asyncio.run(main(record=True))
