"""Record: a two-node voice call, the same call with a single_turn answer node, and legacy LoopAgent."""
import asyncio
import json
from pathlib import Path

from google.adk.agents import Agent, LoopAgent
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from live_harness import RecordingGemini, environment, say_text, spoken, talk, wait_for_turn
from voice_intake import WORKFLOW_MODEL, build_workflow, transcript_by_node

HERE = Path(__file__).parent
RUN_CONFIG = RunConfig(response_modalities=["AUDIO"])
TURNS = ["Hi, I have a question about the docs.", "The sessions page. What happens if I reuse a closed queue?"]


async def call(name, root, turns, timeout=60):
    runner = Runner(app_name="voice_docs", agent=root, session_service=InMemorySessionService())
    session = await runner.session_service.create_session(app_name="voice_docs", user_id="dev")
    entry = {"name": name}
    try:
        rows = await talk(runner, session.id, RUN_CONFIG, turns, timeout=timeout)
    except asyncio.TimeoutError as error:
        rows, entry["error"] = error.rows, f"TimeoutError: no further turn within {timeout} s"
    except Exception as error:
        rows, entry["error"] = [], f"{type(error).__name__}: {str(error).splitlines()[0][:240]}"
    entry["events"] = rows
    entry["by_author"] = transcript_by_node(rows)
    entry["finish_task"] = [c["args"] for r in rows for c in r.get("calls", []) if c["name"] == "finish_task"]
    print(f"[{name}] " + json.dumps(entry["by_author"])[:400] + (f" error={entry['error']}" if "error" in entry else ""))
    return entry


async def main():
    model = RecordingGemini(model=WORKFLOW_MODEL, connections=[])
    happy = await call("two live nodes", build_workflow(model), [say_text(t) for t in TURNS] + [wait_for_turn()])
    happy["connections"] = model.connections
    silent_model = RecordingGemini(model=WORKFLOW_MODEL, connections=[])
    silent = await call("answer node left as single_turn", build_workflow(silent_model, answer_mode=None),
                        [say_text(t) for t in TURNS] + [wait_for_turn()], timeout=45)
    silent["connections"] = silent_model.connections
    loop = await call("LoopAgent under run_live", LoopAgent(name="retry", sub_agents=[
        Agent(name="answer", model=WORKFLOW_MODEL, instruction="Answer briefly.")]), [say_text(TURNS[0])], timeout=20)
    record = {"environment": environment() | {"workflow_model": WORKFLOW_MODEL}, "turns": TURNS,
              "runs": [happy, silent, loop]}
    (HERE / "workflow-run.json").write_text(json.dumps(record, indent=1) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
