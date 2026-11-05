"""Record one long session twice on Gemini: with caching and compaction, and without either.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes recorded-runs.json and run-output.txt. The tests replay the model turns offline.
"""
import asyncio
import json
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from google.adk import Agent  # noqa: E402
from google.adk.agents.context_cache_config import ContextCacheConfig  # noqa: E402
from google.adk.apps.app import App, EventsCompactionConfig  # noqa: E402

import assistant  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTIONS = [
    "Deploy r42 to staging failed. What went wrong, according to its log?",
    "If I roll staging back, does that undo the migration r42 started?",
    "We fixed the migration and deployed r43, which failed differently. What happened?",
    "How long are staging logs kept?",
    "Which of the two failed deploys, r42 or r43, ran its migration to the end?",
    "What is the command to read the full pre_deploy output of r42?",
]


class CacheLog(logging.Handler):
    """Collect ADK's cache-manager messages: they say why a cache was or was not created."""
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        if "gemini_context_cache_manager" in record.name:
            self.lines.append(record.getMessage())


def recording(agent: Agent, calls: list) -> Agent:
    def before(callback_context, llm_request):
        calls.append({"invocation": callback_context.invocation_id, "contents": len(llm_request.contents)})

    def after(callback_context, llm_response):
        content = llm_response.content.model_dump(mode="json", exclude_none=True) if llm_response.content else None
        for part in (content or {}).get("parts", []):
            part.pop("thought_signature", None)
        calls[-1]["turn"] = content
    return agent.clone(update={"before_model_callback": before, "after_model_callback": after})


async def session_run(label: str, cache: bool, compact: bool, agent: Agent = assistant.root_agent,
                      questions: list = QUESTIONS) -> dict:
    calls, log = [], CacheLog()
    logging.getLogger("google_adk").addHandler(log)
    logging.getLogger("google_adk").setLevel(logging.INFO)
    runner = assistant.make_runner(assistant.make_app(recording(agent, calls), cache=cache, compact=compact))
    session = await runner.session_service.create_session(app_name="docs", user_id="dana")
    turns = []
    for n, question in enumerate(questions, 1):
        events = await assistant.ask(runner, session.id, question)
        model_events = [e for e in events if e.usage_metadata]
        answer = next(("".join(p.text or "" for p in e.content.parts if not p.thought).strip()
                       for e in reversed(events) if e.is_final_response() and e.content), "")
        turns.append({"turn": n, "question": question,
                      "tool_calls": [f"{c.name}({c.args})" for e in events for c in e.get_function_calls()],
                      "usage": [assistant.usage(e) for e in model_events], "answer": answer})
    stored = await runner.session_service.get_session(app_name="docs", user_id="dana", session_id=session.id)
    invocations = list(dict.fromkeys(e.invocation_id for e in stored.events if not e.actions.compaction))
    compactions = []
    for e in stored.events:
        if e.actions.compaction:
            c = e.actions.compaction
            covered = sorted({invocations.index(x.invocation_id) + 1 for x in stored.events
                              if not x.actions.compaction and c.start_timestamp <= x.timestamp <= c.end_timestamp})
            compactions.append({"turns": covered, "summary": "".join(p.text or "" for p in c.compacted_content.parts)})
    for call in calls:
        call["turn_index"] = invocations.index(call.pop("invocation")) + 1
    await runner.close()
    logging.getLogger("google_adk").removeHandler(log)
    return {"label": label, "cache": cache, "compact": compact, "turns": turns, "model_calls": calls,
            "compactions": compactions, "stored_events": len(stored.events), "cache_log": log.lines}


async def failures() -> dict:
    out = {}
    # 1. A sliding window needs both numbers; one alone is rejected when the config is built.
    try:
        EventsCompactionConfig(compaction_interval=2)
    except ValueError as error:
        out["half_config"] = str(error).splitlines()[1].strip() if "\n" in str(error) else str(error)
    # 2. A short prefix: with no manual, the cacheable part is below Gemini's minimum cache size.
    short = assistant.root_agent.clone(update={"static_instruction": "You answer questions about docuctl."})
    run = await session_run("short prefix", cache=True, compact=False, agent=short,
                            questions=["What does docuctl rollback do?", "Does it undo migrations?"])
    out["short_prefix"] = {"usage": [u for t in run["turns"] for u in t["usage"]], "cache_log": run["cache_log"]}
    # 3. The App rejects a config object it does not know, so a typo cannot silently turn caching off.
    try:
        App(name="docs", root_agent=assistant.root_agent, context_cache=ContextCacheConfig())
    except ValueError as error:
        out["unknown_field"] = [line for line in str(error).splitlines() if line.strip()][:2]
    return out


def transcript(run: dict) -> str:
    lines = [f"# {run['label']}: cache={run['cache']} compaction={run['compact']}"]
    for t in run["turns"]:
        lines.append(f"> {t['turn']}. {t['question']}")
        lines += [f"call   {c}" for c in t["tool_calls"]]
        lines += [f"model  prompt={u['prompt']} cached={u['cached']} cache={u['cache']}" for u in t["usage"]]
        lines.append("answer " + t["answer"].splitlines()[0][:150])
    lines += [f"compaction of turns {c['turns']}: {len(c['summary'])} characters" for c in run["compactions"]]
    return "\n".join(lines)


async def main() -> None:
    budgeted = await session_run("budgeted", cache=True, compact=True)
    plain = await session_run("plain", cache=False, compact=False)
    record = {"model": assistant.MODEL, "manual_characters": len(assistant.MANUAL),
              "runs": [budgeted, plain], "failures": await failures()}
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (HERE / "run-output.txt").write_text(transcript(budgeted) + "\n\n" + transcript(plain) + "\n", encoding="utf-8")
    print(transcript(budgeted) + "\n\n" + transcript(plain))
    print(json.dumps(record["failures"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
