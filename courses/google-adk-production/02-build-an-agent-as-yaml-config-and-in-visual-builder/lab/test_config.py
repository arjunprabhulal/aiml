"""Check root_agent.yaml, its load failures and the Visual Builder save endpoint, offline.

Run: python -m unittest -v test_config.py
The model is replaced by its recorded responses; the YAML loader, Runner and dev server are real.
"""
import asyncio
import json
import logging
import tempfile
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from fastapi.testclient import TestClient  # noqa: E402
from google.adk.agents.config_agent_utils import from_config  # noqa: E402
from google.adk.cli.fast_api import get_fast_api_app  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

import load  # noqa: E402
import record  # noqa: E402

HERE = Path(__file__).resolve().parent
RECORD = json.loads((HERE / "recorded-runs.json").read_text(encoding="utf-8"))


class ReplayLlm(BaseLlm):
    turns: list

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)["content"]))


def load_text(text: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "root_agent.yaml"
        path.write_text(text, encoding="utf-8")
        return from_config(str(path))


class AgentConfig(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")

    def test_the_yaml_loads_as_an_llm_agent_with_its_tool(self):
        agent = load.load()
        self.assertEqual((type(agent).__name__, agent.name, agent.model), ("LlmAgent", "docs_assistant", RECORD["model"]))
        self.assertEqual([t.__name__ for t in agent.tools], ["read_page"])
        self.assertEqual(agent.generate_content_config.temperature, 0.2)

    def test_the_loaded_agent_runs_through_a_runner(self):
        agent = load.load().clone(update={"model": ReplayLlm(model="replay", turns=list(RECORD["load"]["model_turns"]))})
        events = asyncio.run(load.ask(agent, RECORD["question"]))
        self.assertEqual([load.describe(e) for e in events], RECORD["load"]["lines"])
        self.assertEqual(events[-1].content.parts[-1].text, RECORD["load"]["answer"])

    def test_a_misspelled_field_fails_validation(self):
        with self.assertRaisesRegex(Exception, "instructions\n  Extra inputs are not permitted"):
            load_text(record.BROKEN["misspelled_field"])

    def test_a_missing_tool_function_fails_to_load(self):
        with self.assertRaisesRegex(AttributeError, "has no attribute 'read_pages'"):
            load_text(record.BROKEN["missing_tool"])

    def test_the_loader_blocks_standard_library_references(self):
        with self.assertRaisesRegex(ValueError, "Blocked module reference: 'os.system'"):
            load_text(record.BROKEN["stdlib_tool"])


class VisualBuilderSave(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")
        # The builder writes into the app folder, so the test saves into this folder and restores the file.
        # (A temporary copy would not work here: docs_config also imports from this folder, and the
        # builder blocks an app whose name resolves to code outside its own folder.)
        self.yaml = HERE / "docs_config" / "root_agent.yaml"
        self.app = get_fast_api_app(agents_dir=str(HERE), web=True, session_service_uri="memory://", artifact_service_uri="memory://")
        self.local = TestClient(self.app, client=("127.0.0.1", 50000))

    def tearDown(self):
        self.yaml.write_text(record.YAML, encoding="utf-8")

    def save(self, name: str, http=None):
        files = [("files", ("docs_config/root_agent.yaml", record.UPLOADS[name].encode()))]
        return (http or self.local).post("/dev/apps/docs_config/builder/save", files=files)

    def test_a_builder_save_rewrites_root_agent_yaml(self):
        self.assertEqual(self.local.get("/dev/apps/docs_config/builder").text, record.YAML)
        self.assertEqual(self.save("edit").json(), True)
        self.assertIn("under 80 words", self.yaml.read_text(encoding="utf-8"))

    def test_a_builder_upload_with_an_args_key_is_rejected(self):
        r = self.save("args_key")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(json.dumps(r.json(), separators=(",", ":")), RECORD["builder"]["args_key"].split("\nHTTP")[0])
        self.assertNotIn("args:", self.yaml.read_text(encoding="utf-8"))

    def test_a_builder_upload_naming_code_outside_the_app_is_rejected(self):
        r = self.save("outside_code")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Blocked code reference 'subprocess.run'", r.json()["detail"])

    def test_a_remote_client_cannot_reach_the_builder(self):
        remote = TestClient(self.app, client=("10.0.0.7", 50000))
        r = self.save("edit", http=remote)
        self.assertEqual(r.status_code, 403)
        self.assertIn("ADK_ALLOW_REMOTE_AGENT_BUILDER", r.json()["detail"])
        self.assertNotIn("under 80 words", self.yaml.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
