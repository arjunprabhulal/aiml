"""Run the refinement loop on two changes and save every event and model reply."""
import asyncio
import json
from pathlib import Path

from harness import environment, gemini, run
from refine_entry import build_workflow

HERE = Path(__file__).parent
# (change, does the reviser see the rules?)
RUNS = [("change-rename.txt", True), ("change-config.txt", True), ("change-rename.txt", False)]


async def main():
    runs = []
    for name, sees_rules in RUNS:
        model = gemini()
        events, _ = await run(build_workflow(model, sees_rules), (HERE / name).read_text())
        runs.append({"change": name, "reviser_sees_rules": sees_rules, "events": events,
                     "model_calls": model.calls})
        note = "" if sees_rules else " (reviser without the rules)"
        print(f"$ {name}{note}\n{events[-1]['message']}\n")
    record = {"environment": environment(), "runs": runs}
    (HERE / "refine-run.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
