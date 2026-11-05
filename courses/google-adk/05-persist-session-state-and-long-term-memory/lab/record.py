"""Record two runs of the docs assistant against one SQLite session store, on Gemini.

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
import sqlite3
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from google.adk import Event  # noqa: E402
from google.adk.events import EventActions  # noqa: E402
from google.adk.memory import InMemoryMemoryService  # noqa: E402

import assistant  # noqa: E402

HERE = Path(__file__).resolve().parent
STEPS = [  # (run, user, question): run 2 uses new service objects on the same database file
    (1, "dana", "I'm on docuctl 1.x. How do I roll back production to r41?"),
    (1, "dana", "Which release did you tell me to revert production to earlier?"),
    (2, "dana", "How do I roll back staging to the previous release?"),
    (2, "dana", "Which release did you tell me to revert production to earlier?"),
    (2, "lee", "How do I roll back staging to the previous release?"),
]


def recording_agent(turns: list):
    def keep_turn(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)
    return assistant.root_agent.clone(update={"after_model_callback": keep_turn})


def tables(db: Path) -> dict:
    with sqlite3.connect(db) as con:
        names = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
        counts = {n: con.execute(f'select count(*) from "{n}"').fetchone()[0] for n in names}
        user_state = con.execute("select app_name, user_id, state from user_states").fetchall()
    return {"rows": counts, "user_states": [list(r) for r in user_state]}


async def failures(db_url: str) -> dict:
    out = {}
    service = assistant.DatabaseSessionService(db_url=db_url)
    session = await service.create_session(app_name=assistant.APP, user_id="sam")
    # 1. Writing to a fetched session object is not an event, so nothing is saved.
    session.state["user:docuctl_version"] = "2.x"
    again = await service.get_session(app_name=assistant.APP, user_id="sam", session_id=session.id)
    out["direct_mutation"] = {"local": dict(session.state), "stored": dict(again.state)}
    # 2. Two writers: append through one copy, then through a copy fetched earlier.
    first = await service.get_session(app_name=assistant.APP, user_id="sam", session_id=session.id)
    stale = await service.get_session(app_name=assistant.APP, user_id="sam", session_id=session.id)
    await service.append_event(first, Event(author="docs_assistant", actions=EventActions(state_delta={"note": "a"})))
    try:
        await service.append_event(stale, Event(author="docs_assistant", actions=EventActions(state_delta={"note": "b"})))
        out["stale_session"] = "no error"
    except Exception as error:
        out["stale_session"] = f"{type(error).__name__}: {error}"
    # 3. A required placeholder with no value: the request is never built.
    strict = assistant.root_agent.clone(update={"instruction": assistant.INSTRUCTION.replace("{user:docuctl_version?}", "{user:docuctl_version}")})
    runner = assistant.make_runner(InMemoryMemoryService(), strict, db_url)
    fresh = await runner.session_service.create_session(app_name=assistant.APP, user_id="kim")
    try:
        await assistant.ask(runner, "kim", fresh.id, "How do I deploy?")
        out["missing_placeholder"] = "no error"
    except Exception as error:
        out["missing_placeholder"] = f"{type(error).__name__}: {error}"
    await runner.close()
    return out


async def main() -> None:
    record = {"model": assistant.MODEL, "steps": []}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sessions.db"
        db_url = f"sqlite+aiosqlite:///{db}"
        runners = {}
        for run, user, question in STEPS:
            if run not in runners:
                if runners:
                    await runners[run - 1][0].close()
                memory = InMemoryMemoryService()  # in-process only: a restart starts empty
                turns: list = []
                runners[run] = (assistant.make_runner(memory, recording_agent(turns), db_url), memory, turns)
            runner, memory, turns = runners[run]
            start = len(turns)
            session = await runner.session_service.create_session(app_name=assistant.APP, user_id=user)
            events = await assistant.ask(runner, user, session.id, question)
            stored = await runner.session_service.get_session(app_name=assistant.APP, user_id=user, session_id=session.id)
            await memory.add_session_to_memory(stored)  # this conversation becomes searchable memory
            record["steps"].append({"run": run, "user": user, "question": question, "transcript": assistant.show(events),
                                    "state": dict(stored.state), "model_turns": turns[start:]})
        await runners[2][0].close()
        record["database"] = tables(db)
        record["failures"] = await failures(db_url)
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out = []
    for s in record["steps"]:
        out.append(f'# run {s["run"]}, user {s["user"]}, new session\n> {s["question"]}\n{s["transcript"]}\n')
    (HERE / "run-output.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(json.dumps({"database": record["database"], "failures": record["failures"]}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
