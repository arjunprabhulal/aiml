"""Replay the recorded Gemini drafts through the real gate; no API key needed."""
import asyncio
import copy
import json
import logging
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

from google.adk import Context, Event, Workflow
from google.adk.runners import InMemoryRunner
from google.adk.workflow import node
from google.adk.workflow._errors import WorkflowDataError
from pydantic import ValidationError

from harness import ReplayLlm, reply_to, run
from migration_gate import Decision, apply_migration, build_workflow, create_index, request_approval

logging.getLogger("google_adk").setLevel(logging.CRITICAL)
HERE = Path(__file__).parent
RECORD = json.loads((HERE / "approval-run.json").read_text())
APPROVED, REJECTED = RECORD["runs"]


def without_ids(events):
    """Interrupt ids are fresh UUIDs on every run."""
    events = copy.deepcopy(events)
    for event in events:
        for call in event.get("calls", []):
            call["id"] = call["args"]["interruptId"] = "<id>"
    return events


class Gate:
    """One session of the workflow against a fresh index file."""

    def __init__(self, recorded, calls=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = f"{self.tmp.name}/docs-index.db"
        create_index(self.db_path)
        self.model = ReplayLlm(model=RECORD["environment"]["model"],
                               calls=copy.deepcopy(calls or recorded["model_calls"]))
        self.workflow = build_workflow(self.model)
        self.runner = InMemoryRunner(agent=self.workflow, app_name="docs_assistant")

    def start(self):
        self.paused, self.session_id = asyncio.run(run(
            self.workflow, RECORD["request"], runner=self.runner, state={"db_path": self.db_path}))
        return self.paused

    def resume(self, response, call_id=None):
        call_id = call_id or self.paused[-1]["calls"][0]["id"]
        return asyncio.run(run(self.workflow, reply_to(call_id, response),
                               runner=self.runner, session_id=self.session_id))[0]

    def columns(self):
        with sqlite3.connect(self.db_path) as db:
            return [row[1] for row in db.execute("PRAGMA table_info(pages)")]


class MigrationGate(unittest.TestCase):
    def test_approved_run_replays_and_adds_the_column(self):
        gate = Gate(APPROVED)
        self.assertEqual(without_ids(gate.start()), without_ids(APPROVED["paused"]))
        self.assertEqual(gate.resume(APPROVED["review"]), APPROVED["resumed"])
        self.assertEqual(gate.columns(), APPROVED["columns_after"])
        self.assertIn("section", gate.columns())

    def test_rejected_run_leaves_the_index_unchanged(self):
        gate = Gate(REJECTED)
        gate.start()
        self.assertEqual(gate.resume(REJECTED["review"]), REJECTED["resumed"])
        self.assertEqual(gate.columns(), ["url", "title", "body"])

    def test_resume_does_not_call_the_model_again(self):
        gate = Gate(APPROVED)
        gate.start()
        self.assertEqual(gate.model.calls, [])  # the one recorded draft is used up
        gate.resume(APPROVED["review"])  # a second model call would raise LookupError

    def test_a_reply_to_an_unknown_interrupt_id_is_refused(self):
        gate = Gate(APPROVED)
        gate.start()
        with self.assertRaisesRegex(ValueError, "Function call not found"):
            gate.resume(APPROVED["review"], call_id="not-the-paused-call")
        self.assertNotIn("section", gate.columns())
        self.assertEqual(gate.resume(APPROVED["review"]), APPROVED["resumed"])  # still paused

    def test_a_reply_missing_a_field_fails_on_resume(self):
        gate = Gate(APPROVED)
        gate.start()
        with self.assertRaisesRegex(WorkflowDataError, "reviewer"):
            gate.resume({"verdict": "approve"})

    def test_an_unlisted_verdict_passes_resume_and_fails_in_read_decision(self):
        gate = Gate(APPROVED)
        gate.start()
        with self.assertRaisesRegex(ValidationError, "'approve' or 'reject'"):
            gate.resume({"verdict": "yes", "reviewer": "maya"})
        self.assertNotIn("section", gate.columns())

    def test_sql_outside_the_allowlist_is_refused_before_review(self):
        calls = copy.deepcopy(APPROVED["model_calls"])
        part = calls[0]["reply"]["content"]["parts"][0]
        part["text"] = json.dumps({"summary": "Rebuild the table.", "up_sql": ["DROP TABLE pages"]})
        events = Gate(APPROVED, calls).start()
        self.assertEqual(events[-1]["message"], "Refused before review: ['DROP TABLE pages']")
        self.assertFalse(any("calls" in event for event in events))

    def test_a_second_approval_of_the_same_migration_is_a_no_op(self):
        first = Gate(APPROVED)
        first.start()
        first.resume(APPROVED["review"])
        second = Gate(APPROVED)
        second.db_path = first.db_path
        second.start()
        self.assertIn("was already applied; nothing to do", second.resume(APPROVED["review"])[-1]["message"])

    def test_a_failure_between_statements_rolls_back_the_whole_migration(self):
        gate = Gate(APPROVED)
        migration = {"up_sql": ["ALTER TABLE pages ADD COLUMN section TEXT",
                                "CREATE INDEX idx_missing ON no_such_table (section)"]}
        with self.assertRaisesRegex(sqlite3.OperationalError, "no such table"):
            apply_migration(Decision(verdict="approve", reviewer="maya"), migration, gate.db_path)
        self.assertEqual(gate.columns(), ["url", "title", "body"])  # the ALTER is rolled back too
        with sqlite3.connect(gate.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone(), (0,))

    def test_two_concurrent_approvals_apply_the_migration_once(self):
        gate = Gate(APPROVED)
        migration = APPROVED["paused"][1]["output"]
        both_checked = threading.Barrier(2, timeout=0.5)
        connect = sqlite3.connect

        def connect_and_wait_after_the_check(*args, **kwargs):
            db = connect(*args, **kwargs)

            def trace(sql):  # hold each approval at its first write
                if sql.startswith("ALTER"):
                    try:
                        both_checked.wait()
                    except threading.BrokenBarrierError:
                        pass  # the other approval is waiting for the write lock
            db.set_trace_callback(trace)
            return db

        results, errors = [], []

        def approve(reviewer):
            try:
                event = apply_migration(Decision(verdict="approve", reviewer=reviewer),
                                        migration, gate.db_path)
                results.append(event.message.parts[0].text)
            except Exception as error:
                errors.append(error)

        with mock.patch("migration_gate.sqlite3.connect", connect_and_wait_after_the_check):
            threads = [threading.Thread(target=approve, args=(name,)) for name in ("maya", "li")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted("already applied" in message for message in results), [False, True])
        self.assertEqual(gate.columns(), APPROVED["columns_after"])

    def test_catching_base_exception_continues_without_the_reviewer(self):
        @node(rerun_on_resume=True)
        async def gate_with_fallback(ctx: Context, node_input: str):
            try:
                decision = await ctx.run_node(request_approval, APPROVED["paused"][1]["output"])
            except BaseException as error:  # traps NodeInterruptedError
                yield Event(message=f"caught {type(error).__name__}; treating as rejected")
                return
            yield Event(message=f"reviewer said {decision['verdict']}")

        workflow = Workflow(name="trapped", edges=[("START", gate_with_fallback)])
        events = asyncio.run(run(workflow, "start"))[0]
        self.assertEqual(events[-1]["message"],
                         "caught NodeInterruptedError; treating as rejected")
        self.assertEqual(events[0]["calls"][0]["name"], "adk_request_input")


if __name__ == "__main__":
    unittest.main()
