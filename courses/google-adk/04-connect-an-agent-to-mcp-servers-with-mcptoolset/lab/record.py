"""Run the docs assistant with the MCP task tracker on Gemini and save the runs.

Run from this folder with GOOGLE_API_KEY set: python record.py --record
Writes recorded-runs.json and run-output.txt. The tests replay the model turns offline.
"""
# This comparison makes multiple provider calls and replaces historical files.
# Refuse before importing the SDK or touching any existing record.
import sys
if __name__ == "__main__" and sys.argv[1:] != ["--record"]:
    raise SystemExit("recording is opt-in: use python record.py --record in a separate copy")

import asyncio
import json
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import agent  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTIONS = {
    "add": "The rollback page still mentions docuctl 1.x. Add a docs task to fix it.",
    "filtered": "Mark the API docs task as done.",
    "server-error": "Add a task titled 'ok'.",
}


async def run(key: str) -> dict:
    turns, declarations, results = [], {}, []

    def keep_turn(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)

    def keep_tools(callback_context, llm_request):
        for tool in llm_request.config.tools or []:
            for d in tool.function_declarations or []:
                declarations[d.name] = d.model_dump(mode="json", exclude_none=True)

    def keep_result(tool, args, tool_context, tool_response):
        results.append({"tool": tool.name, "type": type(tool).__name__, "response": tool_response})

    recording = agent.build_agent().clone(update={
        "after_model_callback": keep_turn, "before_model_callback": keep_tools, "after_tool_callback": keep_result})
    events = await agent.ask(QUESTIONS[key], recording)
    return {"question": QUESTIONS[key], "transcript": agent.show(events), "model_turns": turns,
            "declarations": declarations, "tool_results": results}


class Keep(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage().splitlines()[0])


async def failure_bad_command() -> dict:
    """A server that cannot start: ADK logs an error and runs the agent without those tools."""
    keep = Keep()
    logging.getLogger().addHandler(keep)
    events = await agent.ask("List the open tasks.", agent.build_agent(toolset=agent.tracker(python="/no/such/python")))
    logging.getLogger().removeHandler(keep)
    return {"transcript": agent.show(events), "log": [m for m in keep.messages if "will run without" in m][:1]}


async def main() -> None:
    record = {"model": agent.MODEL, "discovery": await agent.list_tools(), "runs": {}}
    for key in QUESTIONS:
        record["runs"][key] = await run(key)
    record["declarations"] = record["runs"]["add"]["declarations"]
    for r in record["runs"].values():
        r.pop("declarations")
    full = agent.tracker(tool_filter=None)
    record["unfiltered"] = sorted(t.name for t in await full.get_tools())
    await full.close()
    record["failures"] = {"bad_command": await failure_bad_command()}
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out = [f"$ python agent.py --tools\n{record['discovery']}\n"]
    for r in record["runs"].values():
        out.append(f'$ python agent.py "{r["question"]}"\n{r["transcript"]}\n')
    (HERE / "run-output.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(record["unfiltered"], record["failures"])


if __name__ == "__main__":
    asyncio.run(main())
