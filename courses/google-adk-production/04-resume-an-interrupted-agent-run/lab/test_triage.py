"""Replay the recorded crash and resume offline, against a temporary SQLite session database.

Run: python -m unittest -v test_triage.py
The model is replaced by its recorded responses. The crash is os._exit replaced by an exception
that ADK does not catch, so the run stops inside file_issue exactly as the killed process did.
"""
import asyncio
import json
import logging
import os
import tempfile
import unittest
import warnings
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

import triage  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))


class Crash(BaseException):
    """Not an Exception, so ADK records no error event: the run just stops, like a killed process."""


class ReplayLlm(BaseLlm):
    turns: list
    calls: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)["content"]))


class Resume(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")
        self.tmp = tempfile.TemporaryDirectory()
        db = f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'sessions.db'}"
        self.tracker = Path(self.tmp.name) / "tracker.json"
        self.model = ReplayLlm(model="replay", turns=list(RECORD["happy"]["model_turns"]))
        agent = triage.root_agent.clone(update={"model": self.model})
        self.patches = [mock.patch.object(triage, "DB_URL", db), mock.patch.object(triage, "TRACKER", self.tracker),
                        mock.patch.object(triage, "app", triage.app.model_copy(update={"root_agent": agent})),
                        mock.patch.object(triage, "root_agent", agent), mock.patch.dict(triage.FAULTS)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def crash(self, idempotency_key: bool = True) -> tuple[str, str]:
        triage.FAULTS.update(crash_after_write=True, idempotency_key=idempotency_key)
        seen = []
        with mock.patch.object(triage.os, "_exit", side_effect=Crash), mock.patch("builtins.print", lambda *a, **k: seen.append(a)):
            with self.assertRaises(Crash):
                asyncio.run(triage.run(None, text=RECORD["report"]))
        triage.FAULTS["crash_after_write"] = False
        return next(a[1] for a in seen if a[0] == "session"), next(a[1] for a in seen if a[0] == "invocation")

    def issues(self) -> list:
        return json.loads(self.tracker.read_text(encoding="utf-8"))

    def test_recorded_process_exits_and_tracker_preserve_the_crash_boundary(self):
        runs = RECORD["runs"]
        self.assertEqual(runs["crash"]["exit"], 137)
        self.assertEqual(runs["resume"]["exit"], 0)
        self.assertEqual(runs["resume_again"]["exit"], 1)
        self.assertEqual(runs["crash"]["tracker"], runs["resume"]["tracker"])
        self.assertEqual(len(runs["resume"]["tracker"]), 1)
        self.assertIn("Dropping function calls", "\n".join(runs["resume"]["stderr"]))

    def test_concurrent_calls_keep_one_issue_per_call_id(self):
        self.tracker.write_text("[]", encoding="utf-8")
        context = SimpleNamespace(function_call_id="same-call")
        triage.FAULTS.update(crash_after_write=False, idempotency_key=True)
        original = Path.read_text
        def slow_read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == self.tracker:
                time.sleep(0.05)
            return value
        with mock.patch.object(Path, "read_text", slow_read), ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: triage.file_issue("Title", "Body", context), range(8)))
        self.assertEqual([i["number"] for i in self.issues()], [1])
        self.assertEqual(sum(not r.get("duplicate_request", False) for r in results), 1)

    def test_failed_replace_preserves_the_previous_tracker(self):
        self.tracker.write_text("[]", encoding="utf-8")
        triage.FAULTS.update(crash_after_write=False, idempotency_key=True)
        with mock.patch.object(triage.os, "replace", side_effect=OSError("write interrupted")):
            with self.assertRaises(OSError):
                triage.file_issue("Title", "Body", SimpleNamespace(function_call_id="a-call"))
        self.assertEqual(self.issues(), [])

    def test_a_page_path_cannot_leave_the_named_docs(self):
        with mock.patch.object(Path, "is_file", return_value=True), mock.patch.object(Path, "read_text", return_value="private"):
            self.assertIn("error", triage.read_page("../secret"))

    def test_resume_reruns_the_interrupted_tool_with_the_same_call_id(self):
        sid, inv = self.crash()
        self.assertEqual(len(self.issues()), 1)
        with mock.patch("builtins.print"):
            events = asyncio.run(triage.resume(sid, inv))
        self.assertEqual([e.invocation_id for e in events], [inv] * len(events))
        self.assertEqual(events[0].get_function_responses()[0].response, {"issue": 1, "duplicate_request": True})
        self.assertTrue(events[-1].actions.end_of_agent)
        self.assertEqual(len(self.issues()), 1)
        self.assertEqual(self.model.calls, 3)  # two before the crash, one for the final answer

    def test_without_the_key_a_resume_files_a_duplicate(self):
        sid, inv = self.crash(idempotency_key=False)
        with mock.patch("builtins.print"):
            asyncio.run(triage.resume(sid, inv))
        self.assertEqual([i["number"] for i in self.issues()], [1, 2])

    def test_a_finished_invocation_is_refused(self):
        sid, inv = self.crash()
        with mock.patch("builtins.print"):
            asyncio.run(triage.resume(sid, inv))
        with self.assertRaisesRegex(SystemExit, "already finished"):
            asyncio.run(triage.resume(sid, inv))
        self.assertEqual(self.model.calls, 3)

    def test_an_unknown_invocation_id_is_refused(self):
        sid, _ = self.crash()
        with self.assertRaisesRegex(SystemExit, "invocation e-0000 is not in session"):
            asyncio.run(triage.resume(sid, "e-0000"))
        self.assertEqual(self.model.calls, 2)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONWARNINGS", "ignore")
    unittest.main()
