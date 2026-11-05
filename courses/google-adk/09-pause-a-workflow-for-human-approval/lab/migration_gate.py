"""Draft a search-index migration with Gemini, pause for a reviewer, then apply or drop it."""
import hashlib
import re
import sqlite3
from contextlib import closing
from typing import Literal

from google.adk import Agent, Event, Workflow
from google.adk.events import RequestInput
from google.genai import types
from pydantic import BaseModel

ALLOWED = re.compile(r"^(ALTER TABLE pages ADD COLUMN|CREATE INDEX) ", re.I)


class Migration(BaseModel):
    summary: str
    up_sql: list[str]


class Decision(BaseModel):
    verdict: Literal["approve", "reject"]
    reviewer: str


def create_index(path: str) -> None:
    """The docs search index the migration changes."""
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, title TEXT, body TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (id TEXT PRIMARY KEY)")


def check_migration(node_input: Migration):
    """Refuse SQL outside the allowlist before a person is asked to review it."""
    refused = [sql for sql in node_input.up_sql if not ALLOWED.match(sql.strip())]
    if refused:
        return Event(message=f"Refused before review: {refused}")  # no route: the run ends
    return Event(route="review", output=node_input, state={"migration": node_input.model_dump()})


def request_approval(node_input: Migration):
    yield RequestInput(message=f"Apply this migration? {node_input.summary}",
                       payload=node_input.model_dump(), response_schema=Decision)


def read_decision(node_input: dict):
    decision = Decision.model_validate(node_input)  # the resume checks fields, not enum values
    return Event(route=decision.verdict, output=decision)


def apply_migration(node_input: Decision, migration: dict, db_path: str):
    """Apply once: the change and its migration id commit together, or neither does."""
    migration_id = hashlib.sha256("\n".join(migration["up_sql"]).encode()).hexdigest()[:12]
    # isolation_level=None stops sqlite3 from opening (and skipping) transactions for us:
    # by default it does not open one before DDL, so each ALTER would commit on its own.
    with closing(sqlite3.connect(db_path, isolation_level=None)) as db:
        db.execute("BEGIN IMMEDIATE")  # take the write lock before the check
        try:
            applied = db.execute("SELECT 1 FROM schema_migrations WHERE id = ?",
                                 (migration_id,)).fetchone()
            if not applied:
                for sql in migration["up_sql"]:
                    db.execute(sql)
                db.execute("INSERT INTO schema_migrations (id) VALUES (?)", (migration_id,))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    if applied:
        return Event(message=f"Migration {migration_id} was already applied; nothing to do.")
    return Event(message=f"Applied migration {migration_id}, approved by {node_input.reviewer}.")


def record_rejection(node_input: Decision):
    return Event(message=f"Migration rejected by {node_input.reviewer}; the index is unchanged.")


def build_workflow(model=None) -> Workflow:
    draft = Agent(
        name="draft_migration",
        model=model or "gemini-3.8-flash",  # or LiteLlm(model="ollama_chat/gemma4:e2b")
        generate_content_config=types.GenerateContentConfig(max_output_tokens=1024),
        output_schema=Migration,
        instruction=(
            "You write SQLite migrations for the docs search index, a table "
            "pages(url TEXT PRIMARY KEY, title TEXT, body TEXT). Return one SQL statement "
            "per list item, without a trailing semicolon, and a one-sentence summary."
        ),
    )
    return Workflow(
        name="migration_gate",
        edges=[
            ("START", draft, check_migration),
            (check_migration, {"review": request_approval}),
            (request_approval, read_decision),
            (read_decision, {"approve": apply_migration, "reject": record_rejection}),
        ],
    )
