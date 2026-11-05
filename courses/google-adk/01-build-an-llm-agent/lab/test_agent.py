"""Offline checks for the real agent definition; no provider requests."""
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from google.adk.agents import Agent

HERE = Path(__file__).resolve().parent


def load_agent(path=HERE / "docs_assistant" / "agent.py"):
    spec = importlib.util.spec_from_file_location("first_agent_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network disabled")):
        spec.loader.exec_module(module)
    return module.root_agent


class FirstAgentTest(unittest.TestCase):
    def test_agent_loads_without_tools_or_network(self):
        agent = load_agent()
        self.assertIsInstance(agent, Agent)
        self.assertEqual(agent.name, "docs_assistant")
        self.assertEqual(agent.tools, [])

    def test_guide_is_loaded_relative_to_agent_file(self):
        agent = load_agent()
        guide = (HERE / "docs_assistant" / "docuctl.md").read_text(encoding="utf-8")
        self.assertIn(guide, agent.instruction)

    def test_practice_commands_exist_in_guide(self):
        cases = json.loads((HERE / "sample-questions.json").read_text())
        guide = (HERE / "docs_assistant" / "docuctl.md").read_text()
        for command in cases["supported"]["commands_to_check"]:
            self.assertIn(command, guide)
        self.assertNotIn("backups", guide)

    def test_output_budget_and_thinking_are_explicit(self):
        config = load_agent().generate_content_config
        self.assertEqual(config.max_output_tokens, 1024)
        self.assertEqual(config.thinking_config.thinking_level.value, "LOW")

    def test_environment_example_has_no_working_key(self):
        env = (HERE / "docs_assistant" / ".env.example").read_text()
        self.assertIn("GOOGLE_API_KEY=replace-with-your-key", env)
        self.assertIn("GOOGLE_GENAI_USE_ENTERPRISE=0", env)
        self.assertIn(".env", (HERE / ".gitignore").read_text().splitlines())

    def test_native_package_exports_agent(self):
        self.assertEqual((HERE / "docs_assistant" / "__init__.py").read_text(), "from . import agent\n")

    def test_missing_guide_fails_during_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "agent.py"
            shutil.copy2(HERE / "docs_assistant" / "agent.py", path)
            with self.assertRaises(FileNotFoundError):
                load_agent(path)

    def test_name_must_be_python_identifier(self):
        with self.assertRaises(ValueError):
            Agent(name="docs-assistant", model="gemini-3.8-flash")


if __name__ == "__main__":
    unittest.main()
