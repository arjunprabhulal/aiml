"""Record the docs assistant on Gemini under each injected fault.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes recorded-runs.json (questions, model turns, tool results, answers) and run-output.txt.
"""
import asyncio
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from google.adk.apps import App  # noqa: E402

import simulated  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTION = "How do I make the assistant use a local model instead of Gemini?"
FIXED = simulated.INSTRUCTION + simulated.ON_ERROR
RUNS = {
    "baseline": dict(fault=None),
    "outage": dict(fault="outage"),
    "outage-with-error-rule": dict(fault="outage", instruction=FIXED),
    "outage-with-retry-plugin": dict(fault="outage", retry="raise"),
    "outage-with-retry-limit-answer": dict(fault="outage", retry="answer"),
    "missing-page-with-error-rule": dict(fault="missing-page", instruction=FIXED),
}

async def run(options: dict) -> dict:
    turns = []

    def keep_turn(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)

    app = simulated.build_app(**options)
    app = App(name=app.name, root_agent=app.root_agent.clone(update={"after_model_callback": keep_turn}),
              plugins=app.plugins)
    events, error = [], None
    try:
        await simulated.ask(app, QUESTION, events)
    except Exception as exc:  # a plugin may end the run by raising
        error = f"{type(exc).__name__}: {exc}"
    lines = simulated.show(events)
    answer = next((l[len("answer "):] for l in reversed(lines) if l.startswith("answer ")), None)
    return {"options": {k: (v == FIXED and "INSTRUCTION + ON_ERROR" or v) for k, v in options.items()},
            "model_turns": turns, "trail": lines, "error": error, "answer": answer,
            "read_page_failures": sum("error_code" in l for l in lines if l.startswith("result read_page")),
            "cites_a_page": bool(answer and answer.rstrip(".").endswith(".md)"))}


async def main() -> None:
    record = {"question": QUESTION, "model": simulated.MODEL, "runs": {}}
    output = []
    for name, options in RUNS.items():
        r = record["runs"][name] = await run(options)
        output.append("\n".join([f"# Run {name}", f"> {QUESTION}", *r["trail"]]
                                + ([f"raised {r['error']}"] if r["error"] else [])) + "\n")
    # The same outage five more times: how often the agent cites a page it never read.
    repeats = [await run(RUNS["outage"]) for _ in range(5)]
    record["outage_repeats"] = [{"read_page_failures": r["read_page_failures"], "cites_a_page": r["cites_a_page"],
                                 "answer": r["answer"]} for r in repeats]
    output.append("# Outage repeated 5 times: read_page failures, cites a page\n" + "\n".join(
        f"{r['read_page_failures']} failures, cites a page: {r['cites_a_page']}  | {r['answer']}" for r in repeats) + "\n")
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=2) + "\n")
    (HERE / "run-output.txt").write_text("\n".join(output))
    print("\n".join(output))


if __name__ == "__main__":
    asyncio.run(main())
