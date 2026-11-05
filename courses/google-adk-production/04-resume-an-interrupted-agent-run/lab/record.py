"""Record a run that dies inside file_issue, its resume, and three ways resuming goes wrong.

Run from this folder with GOOGLE_API_KEY set: python record.py
Each process is a real `python triage.py ...` command against one SQLite session database.
Writes run-output.txt and recorded-runs.json; sessions.db and tracker.json are temporary.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT = "The tokens page says deploy tokens never expire. File a docs issue."
TMP = Path(tempfile.mkdtemp())
ENV = {**os.environ, "GOOGLE_GENAI_USE_ENTERPRISE": "0", "GOOGLE_GENAI_USE_VERTEXAI": "0", "PYTHONWARNINGS": "ignore",
       "DOCS_DB": f"sqlite+aiosqlite:///{TMP / 'sessions.db'}", "DOCS_TRACKER": str(TMP / "tracker.json")}
os.environ.update({k: ENV[k] for k in ("DOCS_DB", "DOCS_TRACKER")})

import triage  # noqa: E402  (reads DOCS_DB and DOCS_TRACKER)


def sh(*args: str) -> dict:
    proc = subprocess.run([sys.executable, "triage.py", *args], cwd=HERE, env=ENV, capture_output=True, text=True, timeout=300)
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    err = [l for l in proc.stderr.splitlines() if l.startswith(("Dropping", "SystemExit")) or l.startswith("invocation ")]
    return {"command": "python triage.py " + " ".join(a if " " not in a else repr(a) for a in args),
            "stdout": lines, "stderr": err, "exit": proc.returncode}


def tracker() -> list:
    path = TMP / "tracker.json"
    return [{"number": i["number"], "key": i["key"]} for i in json.loads(path.read_text())] if path.exists() else []


async def model_turns(session_id: str) -> list:
    """The model's responses as the session stored them, for the offline replay tests."""
    session = await triage.DatabaseSessionService(db_url=ENV["DOCS_DB"]).get_session(
        app_name=triage.APP, user_id=triage.USER, session_id=session_id)
    turns = []
    for e in session.events:
        if e.content and e.content.role == "model" and e.author == triage.APP:
            parts = [{k: v for k, v in p.model_dump(mode="json", exclude_none=True).items() if k != "thought_signature"}
                     for p in e.content.parts]
            turns.append({"invocation": e.invocation_id, "content": {"role": "model", "parts": parts}})
    return turns


def ids(run: dict) -> tuple[str, str]:
    return (next(l.split()[1] for l in run["stdout"] if l.startswith("session ")),
            next(l.split()[1] for l in run["stdout"] if l.startswith("invocation ")))


def main() -> None:
    rec = {"model": triage.MODEL, "report": REPORT, "runs": {}}
    crash = sh("start", "--crash-after-write", REPORT)
    sid, inv = ids(crash)
    rec["runs"]["crash"] = {**crash, "tracker": tracker()}
    rec["runs"]["resume"] = {**sh("resume", sid, inv), "tracker": tracker()}
    rec["runs"]["resume_again"] = {**sh("resume", sid, inv), "tracker": tracker()}
    rec["runs"]["unknown_invocation"] = {**sh("resume", sid, "e-0000"), "tracker": tracker()}
    rec["happy"] = {"session": sid, "invocation": inv, "model_turns": asyncio.run(model_turns(sid))}

    # What the guard prevents: the same two resumes, unguarded, call the model again.
    events = asyncio.run(triage.run(sid, invocation_id=inv))
    rec["unguarded_resume"] = [triage.describe(e) for e in events]

    (TMP / "tracker.json").unlink()
    crash = sh("start", "--crash-after-write", "--no-idempotency-key", REPORT)
    sid2, inv2 = ids(crash)
    rec["runs"]["crash_no_key"] = {**crash, "tracker": tracker()}
    rec["runs"]["resume_no_key"] = {**sh("resume", "--no-idempotency-key", sid2, inv2), "tracker": tracker()}
    rec["no_key"] = {"model_turns": asyncio.run(model_turns(sid2))}

    out = []
    for name, run in rec["runs"].items():
        out += [f"$ {run['command']}", *run["stderr"], *run["stdout"], f"exit {run['exit']}; tracker: {run['tracker']}", ""]
    out += ["# the second resume without check_resumable", *rec["unguarded_resume"]]
    text = "\n".join(out).replace(sid, "SESSION").replace(sid2, "SESSION2")
    (HERE / "run-output.txt").write_text(text + "\n", encoding="utf-8")
    raw = json.dumps(rec, indent=2, ensure_ascii=False).replace(sid, "SESSION").replace(sid2, "SESSION2")
    (HERE / "recorded-runs.json").write_text(raw + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
