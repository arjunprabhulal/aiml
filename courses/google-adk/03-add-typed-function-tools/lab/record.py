"""Run the docs assistant on Gemini and save every call, result, approval and model turn.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes recorded-runs.json and run-output.txt. The tests replay the model turns offline.
"""
import asyncio
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from google.adk import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402

import agent  # noqa: E402
import docs_tools  # noqa: E402

HERE = Path(__file__).resolve().parent
STALE = "The rollback page still mentions the docuctl 1.x command. Check it and file an outdated-docs issue."
SCENARIOS = [
    ("approved", STALE, True),
    ("declined", STALE, False),
    ("declined-retry", STALE, False),
    ("too-many", "Search the docs for docuctl and list 20 matching pages.", True),
    ("short-summary", "File an unclear issue on the tokens page with the summary 'expiry?'.", True),
    ("unknown-page", "File an incorrect issue on the install page: the pipx command fails.", True),
]


def steps_of(event) -> list[dict]:
    rows = [{"call": c.name, "args": c.args} for c in event.get_function_calls()]
    rows += [{"result": r.name, "response": r.response} for r in event.get_function_responses()]
    if agent.answer_text(event):
        rows.append({"answer": agent.answer_text(event)})
    return rows


async def run(name: str, text: str, decision: bool) -> dict:
    docs_tools.ISSUES.clear()
    turns, declarations = [], {}

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

    update = {"after_model_callback": keep_turn, "before_model_callback": keep_tools}
    if name == "declined-retry":  # the instruction without its last sentence about rejected calls
        update["instruction"] = agent.INSTRUCTION.rsplit("\n", 1)[0]
    recording = agent.build_agent().clone(update=update)
    sessions = InMemorySessionService()
    runner = Runner(app_name="docs", agent=recording, session_service=sessions)
    session = await sessions.create_session(app_name="docs", user_id="dev")
    asked = []

    def approve(tool: str, args: dict) -> bool:
        asked.append({"tool": tool, "args": args, "approved": decision})
        return decision

    events = await agent.ask(runner, session.id, text, approve)
    await runner.close()
    return {"scenario": name, "prompt": text, "approve": decision,
            "steps": [row for event in events for row in steps_of(event)],
            "approvals": asked, "issues": list(docs_tools.ISSUES), "model_turns": turns,
            "declarations": declarations}


def transcript(runs: list[dict]) -> list[str]:
    """What agent.py prints for each run, with page text and the confirmation payload shortened."""
    lines = []
    for r in runs:
        lines.append(f'$ python agent.py "{r["prompt"]}"' + ("" if r["approve"] else "   # answer N"))
        for step in r["steps"]:
            if "answer" in step:
                lines.append(f"answer   {step['answer']}")
            elif step.get("call") == agent.CONFIRM:
                lines.append(f"call     {agent.CONFIRM} for {step['args']['originalFunctionCall']['name']}")
            elif "call" in step:
                lines.append(f"call     {step['call']} {step['args']}")
            else:
                shown = sorted(step["response"]) if "text" in step["response"] else step["response"]
                lines.append(f"result   {step['result']} {shown}")
        lines.append(f"# approvals asked: {len(r['approvals'])}, issues filed: {[i['id'] for i in r['issues']]}")
        lines.append("")
    return lines


async def main() -> None:
    runs = [await run(*s) for s in SCENARIOS]
    declarations = runs[0].pop("declarations")
    for r in runs[1:]:
        r.pop("declarations")
    record = {"model": agent.MODEL, "declarations": declarations, "runs": runs}
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = transcript(runs)
    (HERE / "run-output.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
