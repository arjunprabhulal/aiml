"""Replay the recorded Gemini turns against the real SkillToolset, offline.

Run: python -m unittest -v test_agent.py
The model is replaced by its recorded turns; skill loading, the skill tools, the script run and the agent loop are real.
"""
import asyncio
import json
import logging
import shutil
import tempfile
from unittest.mock import patch
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.skills import load_skill_from_dir  # noqa: E402
from google.adk.tools.skill_toolset import SkillDiscoveryMode, SkillToolset  # noqa: E402
from google.genai import types  # noqa: E402

import agent  # noqa: E402

HERE = Path(__file__).resolve().parent
RECORD = json.loads((HERE / "recorded-runs.json").read_text(encoding="utf-8"))


class ReplayLlm(BaseLlm):
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def replay(turns: list, toolset=None) -> tuple[str, ReplayLlm]:
    model = ReplayLlm(model="replay", turns=list(turns), requests=[])
    toolset = toolset or agent.skills_toolset(folder=HERE / "skills")
    events = asyncio.run(agent.ask("replayed question", agent.build_agent(model, toolset)))
    return agent.show(events), model


def setUpModule():
    warnings.simplefilter("ignore")  # unittest resets warning filters before the tests run


def offered(request) -> list[str]:
    return sorted(d.name for t in request.config.tools for d in t.function_declarations)


def call(name: str, **args) -> dict:
    return {"role": "model", "parts": [{"function_call": {"name": name, "args": args}}]}


class SkillToolsetTests(unittest.TestCase):
    def test_the_folder_loads_both_skills(self):
        self.assertEqual(sorted(s.name for s in agent.load_skills_from_dir(HERE / "skills")), sorted(RECORD["skills"]))

    def test_release_notes_follow_the_skill_and_run_its_script(self):
        run = RECORD["runs"]["release"]
        transcript, _ = replay(run["model_turns"])
        self.assertEqual(transcript, run["transcript"])
        self.assertIn('result run_skill_script {\'skill_name\': \'release-notes\', \'file_path\': \'scripts/group_changes.py\', \'stdout\': \'{"breaking": ["remove the deprecated', transcript)
        self.assertNotIn("cache the Go toolchain (#221)", transcript)

    def test_list_merged_prs_is_offered_only_after_the_skill_loads(self):
        _, model = replay(RECORD["runs"]["release"]["model_turns"])
        self.assertNotIn("list_merged_prs", offered(model.requests[0]))
        self.assertIn("list_merged_prs", offered(model.requests[2]))

    def test_eager_discovery_puts_the_catalog_in_the_instruction(self):
        eager = SkillToolset(skills=agent.load_skills_from_dir(HERE / "skills"), discovery_mode=SkillDiscoveryMode.EAGER)
        _, model = replay([{"role": "model", "parts": [{"text": "ok"}]}], eager)
        self.assertNotIn("list_skills", offered(model.requests[0]))
        self.assertIn("release-notes", model.requests[0].config.system_instruction)

    def test_a_folder_named_differently_from_its_skill_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(HERE / "skills" / "release-notes", Path(tmp) / "release_notes")
            with self.assertRaises(ValueError) as caught:
                load_skill_from_dir(Path(tmp) / "release_notes")
        self.assertEqual(f"ValueError: {caught.exception}", RECORD["failures"]["name_mismatch"])

    def test_without_a_code_executor_the_script_never_runs(self):
        run = RECORD["runs"]["no-executor"]
        transcript, model = replay(run["model_turns"], agent.skills_toolset(folder=HERE / "skills", run_scripts=False))
        self.assertEqual(transcript, run["transcript"])
        self.assertTrue(all("run_skill_script" not in offered(r) for r in model.requests))
        self.assertNotIn("call   run_skill_script", transcript)
        self.assertIn("call   load_skill_resource {'skill_name': 'release-notes', 'file_path': 'scripts/group_changes.py'}", transcript)

    def test_resource_paths_cannot_leave_the_skill(self):
        turns = [call("load_skill_resource", skill_name="release-notes", file_path="references/../../../agent.py"),
                 call("load_skill_resource", skill_name="release-notes", file_path="../agent.py"),
                 {"role": "model", "parts": [{"text": "stopped"}]}]
        transcript, _ = replay(turns)
        self.assertIn("'error_code': 'RESOURCE_NOT_FOUND'", transcript)
        self.assertIn("'error_code': 'INVALID_RESOURCE_PATH'", transcript)
        self.assertNotIn("MERGED", transcript)

    def test_an_unknown_version_stops_the_skill(self):
        run = RECORD["runs"]["unknown-version"]
        transcript, _ = replay(run["model_turns"])
        self.assertEqual(transcript, run["transcript"])
        self.assertNotIn("run_skill_script", transcript)


class DocsPathSafety(unittest.TestCase):
    def test_read_page_refuses_an_out_of_tree_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "outside.txt").write_text("private content")
            (root / "docs/config.md").symlink_to(root / "outside.txt")
            with patch.object(agent, "HERE", root), patch.object(agent, "PAGES", ["config"]):
                result = agent.read_page("config")
            self.assertIn("error", result)
            self.assertNotIn("private content", str(result))


if __name__ == "__main__":
    unittest.main()
