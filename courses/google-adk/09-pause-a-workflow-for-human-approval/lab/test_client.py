import asyncio
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
HERE = Path(__file__).parent


import sqlite3
from pydantic import ValidationError
import approval_client
from harness import ReplayLlm
from test_migration_gate import RECORD

class InteractiveReview(unittest.TestCase):
    def options(self, db):
        return approval_client.parse_options(["--db", str(db), "--reviewer", "local-reviewer"])

    def replay(self, row):
        return ReplayLlm(model=RECORD["environment"]["model"], calls=copy.deepcopy(row["model_calls"]))

    def test_sql_is_presented_and_no_column_exists_before_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "new.db"; model = self.replay(RECORD["runs"][0]); seen = []
            async def review(payload):
                with sqlite3.connect(path) as db: self.assertNotIn("section", [r[1] for r in db.execute("PRAGMA table_info(pages)")])
                seen.append(payload); return "approve"
            result = asyncio.run(approval_client.run_one(self.options(path), model, review))
            self.assertEqual(seen[0]["up_sql"], RECORD["runs"][0]["paused"][1]["output"]["up_sql"])
            self.assertIn("section", result["columns_after"]); self.assertEqual(model.calls, [])

    def test_rejection_resumes_same_pending_call_and_keeps_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = RECORD["runs"][1]; model = self.replay(row)
            async def review(payload): return "reject"
            result = asyncio.run(approval_client.run_one(self.options(Path(tmp) / "new.db"), model, review))
            self.assertEqual(result["columns_after"], ["url", "title", "body"])
            self.assertIn("rejected", result["resumed_events"][-1]["message"])
            self.assertEqual(model.calls, [])

    def test_existing_database_is_preserved_before_any_provider_setup(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(approval_client, "build_workflow") as factory:
            path = Path(tmp) / "existing.db"; path.write_bytes(b"original bytes")
            with self.assertRaises(FileExistsError): asyncio.run(approval_client.run_one(self.options(path)))
            self.assertEqual(path.read_bytes(), b"original bytes"); factory.assert_not_called()

    def test_cancelled_review_leaves_the_index_without_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "new.db"
            async def review(payload): raise EOFError("no decision")
            with self.assertRaises(EOFError): asyncio.run(approval_client.run_one(self.options(path), self.replay(RECORD["runs"][0]), review))
            with sqlite3.connect(path) as db: self.assertNotIn("section", [r[1] for r in db.execute("PRAGMA table_info(pages)")])

    def test_interactive_prompt_sends_no_invalid_verdict(self):
        with patch("builtins.input", side_effect=["yes", "approve"]):
            self.assertEqual(asyncio.run(approval_client.review_payload({"up_sql": ["actual draft"]})), "approve")

    def test_blank_reviewer_or_request_refused_before_activity(self):
        for args in [["--reviewer", " "], ["--reviewer", "x", "--request", " "]]:
            with self.assertRaises(SystemExit): approval_client.parse_options(args)

if __name__ == "__main__": unittest.main()
