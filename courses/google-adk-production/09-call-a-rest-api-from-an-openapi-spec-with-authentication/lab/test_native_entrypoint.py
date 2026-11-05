"""Check the native package without a model, keeping the original dynamic toolset."""
import asyncio
import importlib
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from google.adk.apps import App
from google.adk.cli.utils.agent_loader import AgentLoader
import assistant
import ship_api

class NativeEntrypoint(unittest.TestCase):
    def test_native_app_preserves_authenticated_filtered_dynamic_tools(self):
        spec = ship_api.app.openapi()
        spec["servers"] = [{"url": "http://127.0.0.1:8766"}]
        with patch.dict(os.environ, {"SHIP_API_KEY": "local-test-only"}), patch.object(assistant, "load_spec", return_value=spec) as load:
            app = AgentLoader(str(Path(__file__).parent)).load_agent("release_assistant")
        self.assertIsInstance(app, App)
        self.assertEqual(app.name, "release_assistant")
        load.assert_called_once_with()
        tools = app.root_agent.tools[0]
        self.assertEqual(tools.tool_filter, assistant.READ_ONLY)
        self.assertIs(tools._header_provider, assistant.request_id)
        self.assertEqual(app.root_agent.instruction, assistant.INSTRUCTION)
        generated = asyncio.run(tools.get_tools())
        self.assertEqual([t.name for t in generated], ["list_releases", "get_release"])
        self.assertEqual(tools._auth_credential.api_key, "local-test-only")
        self.assertEqual(tools._auth_scheme.name, "X-Ship-Key")

    def test_recording_requires_explicit_opt_in_before_model_or_service_work(self):
        result = subprocess.run([sys.executable, "record.py"], cwd=Path(__file__).parent, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("recording is opt-in", result.stderr)

if __name__ == "__main__":
    unittest.main()
