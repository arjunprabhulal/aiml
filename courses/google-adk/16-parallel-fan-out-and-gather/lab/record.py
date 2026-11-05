"""Run both fan-out workflows on Gemini and save every event, model reply, timing and error."""
import asyncio
import json
import time
from pathlib import Path

from harness import environment, gemini, run
from release_prep import build_graph, build_partial

HERE = Path(__file__).parent
# (workflow, release file); 3.6.0 has no built site, so check_links raises.
RUNS = [("graph", "release-3.5.0.md"), ("graph", "release-3.6.0.md"),
        ("partial", "release-3.6.0.md")]


async def main():
    runs = []
    for kind, name in RUNS:
        model = gemini()
        workflow = (build_graph if kind == "graph" else build_partial)(model)
        events, error = [], None
        started = time.perf_counter()
        try:
            events, _ = await run(workflow, (HERE / name).read_text())
        except Exception as exc:  # the fail-all run: record the error the caller sees
            error = f"{type(exc).__name__}: {exc}"
        seconds = round(time.perf_counter() - started, 2)
        runs.append({"workflow": kind, "release": name, "events": events, "error": error,
                     "model_calls": model.calls, "run_seconds": seconds})
        print(f"$ {kind} workflow, {name}\n{error or events[-1]['message']}\n")
    record = {"environment": environment(), "runs": runs}
    (HERE / "prep-run.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
