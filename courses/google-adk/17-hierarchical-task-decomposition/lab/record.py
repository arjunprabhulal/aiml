"""Run the three-level tree on Gemini and save the events, the delegation log and model replies."""
import asyncio
import json
import time
from pathlib import Path

from harness import environment, gemini, run
from upgrade_guide import DelegationLog, build_workflow

HERE = Path(__file__).parent
USAGE = ("prompt_token_count", "candidates_token_count", "thoughts_token_count")
GOAL = "Write the upgrade guide for moving a docs site from docuctl 3.4 to 3.6."


async def main():
    runs = []
    # Three trials per depth: the number of calls a tree makes varies from run to run.
    for depth, trial in [(d, t) for d in (3, 2) for t in (1, 2, 3)]:
        model, log = gemini(), DelegationLog(max_model_calls=24)
        started = time.perf_counter()
        events, error = [], None
        try:
            events, _ = await asyncio.wait_for(
                run(build_workflow(model, max_depth=depth), GOAL, plugins=[log]),
                timeout=180,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        calls = model.calls
        if (depth, trial) != (2, 1):  # timing and token usage only; tests replay depth 2, trial 1
            calls = [{"system": c["system"], "latency_s": c["latency_s"],
                      "usage": {k: v for k, v in c["reply"].get("usage_metadata", {}).items()
                                if k in USAGE}} for c in calls]
        runs.append({"max_depth": depth, "trial": trial, "events": events, "error": error,
                     "delegation": log.rows, "model_calls": calls,
                     "run_seconds": round(time.perf_counter() - started, 2)})
        print(f"$ max_depth={depth}, trial {trial}: {len(calls)} model calls, "
              f"{runs[-1]['run_seconds']} s")
        if trial == 1:
            print(f"{error or events[-1]['message']}\n")
    record = {"environment": environment(), "input": GOAL, "runs": runs}
    (HERE / "guide-run.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
