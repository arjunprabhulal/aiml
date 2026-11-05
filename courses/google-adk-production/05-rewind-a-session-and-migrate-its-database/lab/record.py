"""Record the rewind demo on Gemini and the session-database migration commands.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes run-output.txt and recorded-runs.json. Databases are created in a temporary folder.
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

TMP = Path(tempfile.mkdtemp())
os.environ["DOCS_DB"] = f"sqlite+aiosqlite:///{TMP / 'sessions.db'}"

import check_migrated  # noqa: E402
import legacy  # noqa: E402
import pins  # noqa: E402

HERE = Path(__file__).resolve().parent
ADK = str(Path(sys.executable).with_name("adk"))
TURNS = ["I'm on the payments team. Pin the rollback page.",
         "Pin the tokens page too. And I moved to the platform team.",
         "Which pages are pinned, and which team am I on?"]


async def rewind_demo() -> dict:
    runner = pins.build_runner()
    session = await runner.session_service.create_session(app_name=pins.APP, user_id=pins.USER)
    rec = {"snapshots": {}, "turns": TURNS}
    try:
        await pins.ask(runner, session.id, TURNS[0])
        rec["snapshots"]["after turn 1"] = await pins.snapshot(runner, session.id)
        second = await pins.ask(runner, session.id, TURNS[1])
        rec["snapshots"]["after turn 2"] = await pins.snapshot(runner, session.id)
        rec["rewound_invocation"] = second[0].invocation_id
        await runner.rewind_async(user_id=pins.USER, session_id=session.id, rewind_before_invocation_id=second[0].invocation_id)
        rec["snapshots"]["after rewind"] = await pins.snapshot(runner, session.id)
        third = await pins.ask(runner, session.id, TURNS[2])
        rec["answer"] = third[-1].content.parts[-1].text
        stored = await runner.session_service.get_session(app_name=pins.APP, user_id=pins.USER, session_id=session.id)
        rec["rewind_event"] = next(e.actions.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
                                   for e in stored.events if e.actions.rewind_before_invocation_id)
        rec["model_turns"] = [{"content": {"role": "model", "parts": [
            {k: v for k, v in p.model_dump(mode="json", exclude_none=True).items() if k != "thought_signature"}
            for p in e.content.parts]}} for e in stored.events if e.content and e.content.role == "model"]
        try:
            await runner.rewind_async(user_id=pins.USER, session_id=session.id, rewind_before_invocation_id="e-0000")
        except Exception as exc:  # recorded failure
            rec["unknown_invocation"] = f"{type(exc).__name__}: {exc}"
    finally:
        await runner.close()
    return rec


def sh(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, cwd=TMP, capture_output=True, text=True, timeout=120)
    lines = [re.sub(r"^\d{4}-\d\d-\d\d [\d:,]+ - ", "", l) for l in (proc.stderr + proc.stdout).splitlines()
             if l.strip() and not l.startswith(" ")]
    lines = [l[:260] + (" …" if len(l) > 260 else "") for l in lines]
    shown = ["adk", *cmd[1:]] if cmd[0] == ADK else ["python", *[Path(a).name if a.endswith(".py") else a for a in cmd[1:]]]
    return {"command": " ".join(shown), "lines": lines, "exit": proc.returncode}


def migrations() -> dict:
    py = sys.executable
    runs = {
        "build": sh([py, str(HERE / "legacy.py"), "legacy.db"]),
        "migrate": sh([ADK, "migrate", "session", "--source_db_url", "sqlite:///legacy.db", "--dest_db_url", "sqlite:///migrated.db"]),
        "check": sh([py, str(HERE / "check_migrated.py"), "migrated.db"]),
        "migrate_unsafe": sh([ADK, "migrate", "session", "--source_db_url", "sqlite:///legacy.db",
                              "--dest_db_url", "sqlite:///migrated-full.db", "--allow-unsafe-unpickling"]),
        "check_unsafe": sh([py, str(HERE / "check_migrated.py"), "migrated-full.db"]),
        "in_place": sh([ADK, "migrate", "session", "--source_db_url", "sqlite:///legacy.db", "--dest_db_url", "sqlite:///legacy.db"]),
        "typo": sh([ADK, "migrate", "session", "--source_db_url", "sqlite:///legacy-db.db", "--dest_db_url", "sqlite:///out.db"]),
    }
    runs["typo"]["created"] = sorted(p.name for p in TMP.glob("*.db"))
    return runs


def main() -> None:
    rec = {"model": pins.MODEL, "rewind": asyncio.run(rewind_demo()), "migrate": migrations()}
    r = rec["rewind"]
    out = ["$ python pins.py", *[f"{k}: {v}" for k, v in r["snapshots"].items()], f"turn 3: {r['answer']}", "",
           "# runner.rewind_async(..., rewind_before_invocation_id='e-0000')", r["unknown_invocation"], ""]
    for run in rec["migrate"].values():
        out += [f"$ {run['command']}", *run["lines"], f"exit {run['exit']}", ""]
    out.append(f"files now: {rec['migrate']['typo']['created']}")
    text = "\n".join(out)
    (HERE / "run-output.txt").write_text(text + "\n", encoding="utf-8")
    (HERE / "recorded-runs.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
