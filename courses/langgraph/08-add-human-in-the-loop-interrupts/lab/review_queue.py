"""A small pull-request queue, two read-only tools and one tool that writes: posting a review comment."""
import os
import sqlite3
from contextlib import closing

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

PULL_REQUESTS = {
    412: {"title": "Retry webhook delivery on 503", "ci": "passed",
          "diff": "webhooks/sender.py: wrap post() in a loop of 3 attempts with 2s backoff on HTTP 503\n"
                  "tests/test_sender.py: add test_retries_on_503"},
    415: {"title": "Raise the default HTTP timeout to 30s",
          "ci": "failed: tests/test_client.py::test_default_timeout expected 10, got 30",
          "diff": "client/http.py: DEFAULT_TIMEOUT = 10 -> DEFAULT_TIMEOUT = 30"},
    418: {"title": "Remove the unused legacy CSV export", "ci": "passed",
          "diff": "export/csv_legacy.py: deleted (212 lines)\nexport/__init__.py: drop csv_legacy import"},
}
# Stands in for the code host's API. Comments are rows in a SQLite file, so they outlive the process,
# and the tool call ID is stored with each one as a unique idempotency key.
CODE_HOST_DB = os.environ.get("CODE_HOST_DB", "code_host.sqlite")


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(CODE_HOST_DB)
    db.execute("CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY, number INTEGER NOT NULL,"
               " body TEXT NOT NULL, tool_call_id TEXT NOT NULL UNIQUE)")
    return db


def posted() -> list[dict]:
    """Every comment the code host holds, oldest first."""
    with closing(connect()) as db:
        rows = db.execute("SELECT number, body, tool_call_id FROM comments ORDER BY id").fetchall()
    return [{"number": n, "body": b, "tool_call_id": i} for n, b, i in rows]


def clear() -> None:
    with closing(connect()) as db, db:
        db.execute("DELETE FROM comments")


@tool
def get_diff(number: int) -> str:
    """Get the changed files and a one-line summary of each change for a pull request."""
    return PULL_REQUESTS[number]["diff"]


@tool
def get_ci_status(number: int) -> str:
    """Get the CI result for a pull request: 'passed', or 'failed:' and the failing test."""
    return PULL_REQUESTS[number]["ci"]


@tool
def post_review_comment(number: int, body: str, runtime: ToolRuntime) -> str:
    """Post a review comment on a pull request. Other developers see it immediately."""
    # The tool call ID is the idempotency key. The UNIQUE constraint checks it and the insert commits in
    # one statement, so a replay of the same approved call posts nothing, even from a new process.
    with closing(connect()) as db, db:
        row = db.execute("INSERT INTO comments (number, body, tool_call_id) VALUES (?, ?, ?)"
                         " ON CONFLICT (tool_call_id) DO NOTHING", (number, body, runtime.tool_call_id))
    if row.rowcount == 0:
        return f"Already posted on #{number}."
    return f"Posted comment {row.lastrowid} on #{number}."
