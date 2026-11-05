"""Replay the rewind demo offline, and run the session migration CLI on a fresh legacy database.

Run: python -m unittest -v test_pins.py
The model is replaced by its recorded responses; the Runner, DatabaseSessionService, rewind and
`adk migrate session` are real. Nothing here calls a model or the network.
"""
import asyncio
import json
import logging
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

import check_migrated  # noqa: E402
import legacy  # noqa: E402
import pins  # noqa: E402

HERE = Path(__file__).resolve().parent
RECORD = json.loads((HERE / "recorded-runs.json").read_text(encoding="utf-8"))
ADK = str(Path(sys.executable).with_name("adk"))


class ReplayLlm(BaseLlm):
    turns: list

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)["content"]))


class Rewind(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")
        self.tmp = tempfile.TemporaryDirectory()
        model = ReplayLlm(model="replay", turns=list(RECORD["rewind"]["model_turns"]))
        self.agent = pins.root_agent.clone(update={"model": model})

    def tearDown(self):
        self.tmp.cleanup()

    def run_demo(self, rewind_to_unknown: bool = False):
        with mock.patch.object(pins, "root_agent", self.agent):
            runner = pins.build_runner(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'sessions.db'}")

        async def go():
            session = await runner.session_service.create_session(app_name=pins.APP, user_id=pins.USER)
            try:
                await pins.ask(runner, session.id, RECORD["rewind"]["turns"][0])
                second = await pins.ask(runner, session.id, RECORD["rewind"]["turns"][1])
                target = "e-0000" if rewind_to_unknown else second[0].invocation_id
                await runner.rewind_async(user_id=pins.USER, session_id=session.id, rewind_before_invocation_id=target)
                return await pins.snapshot(runner, session.id)
            finally:
                await runner.close()

        return asyncio.run(go())

    def test_rewind_restores_session_state_and_the_artifact(self):
        snap = self.run_demo()
        expected = RECORD["rewind"]["snapshots"]["after rewind"]
        self.assertEqual((snap["pinned"], snap["artifact"]), (expected["pinned"], expected["artifact"]))
        self.assertEqual(snap["artifact_versions"], expected["artifact_versions"])  # restored as a new version

    def test_user_state_is_not_restored(self):
        snap = self.run_demo()
        self.assertEqual(snap["user:team"], "platform")
        self.assertEqual(RECORD["rewind"]["snapshots"]["after turn 1"]["user:team"], "payments")

    def test_rewound_events_stay_in_the_log(self):
        snap = self.run_demo()
        self.assertEqual(snap["events"], RECORD["rewind"]["snapshots"]["after turn 2"]["events"] + 1)

    def test_an_unknown_invocation_id_raises(self):
        from google.adk.errors._invocation_not_found_error import InvocationNotFoundError
        with self.assertRaisesRegex(InvocationNotFoundError, "Invocation ID not found: e-0000"):
            self.run_demo(rewind_to_unknown=True)


class Migrate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        asyncio.run(legacy.build(str(cls.dir / "legacy.db")))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        warnings.simplefilter("ignore")

    def migrate(self, source: str, dest: str, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([ADK, "migrate", "session", "--source_db_url", f"sqlite:///{source}",
                               "--dest_db_url", f"sqlite:///{dest}", *extra], cwd=self.dir, capture_output=True, text=True)

    def deltas(self, name: str) -> list[str]:
        return [l for l in asyncio.run(check_migrated.check(str(self.dir / name))) if l.startswith("event e-2 docs")]

    def test_a_restricted_migration_drops_an_event_it_cannot_unpickle(self):
        proc = self.migrate("legacy.db", "migrated.db")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Refusing to load collections.Counter", proc.stderr)
        self.assertEqual(self.deltas("migrated.db"), ["event e-2 docs_assistant  state_delta={}"])

    def test_allow_unsafe_unpickling_keeps_the_event(self):
        proc = self.migrate("legacy.db", "migrated-full.db", "--allow-unsafe-unpickling")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("page_views", self.deltas("migrated-full.db")[0])

    def test_in_place_migration_is_refused(self):
        proc = self.migrate("legacy.db", "legacy.db")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("In-place migration is not supported", proc.stdout + proc.stderr)

    def test_a_misspelled_source_path_reports_no_migration_needed(self):
        proc = self.migrate("legacy-db.db", "out.db")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("already at latest version 1. No migration needed.", proc.stderr)
        self.assertTrue((self.dir / "legacy-db.db").exists())
        self.assertFalse((self.dir / "out.db").exists())


if __name__ == "__main__":
    unittest.main()
