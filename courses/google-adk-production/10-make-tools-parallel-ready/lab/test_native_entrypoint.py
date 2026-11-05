"""Native async package and programmatic RunConfig selection, with no model requests."""
import asyncio
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from google.adk.cli.utils.agent_loader import AgentLoader
import assistant

class NativeEntrypoint(unittest.TestCase):
    def test_native_package_uses_the_async_tool(self):
        agent = AgentLoader(str(Path(__file__).parent)).load_agent("docs_checker")
        self.assertEqual(agent.tools, [assistant.fetch_page])
        self.assertIn("fetch_page", agent.instruction)

    def test_programmatic_sync_selection_preserves_worker_pool_config(self):
        options = assistant.parse_options(["--tool", "sync", "--workers", "2", "Check rollback and hooks"])
        agent, config = assistant.selected_run(options)
        self.assertEqual(agent.tools, [assistant.fetch_page_blocking])
        self.assertEqual(config.tool_thread_pool_config.max_workers, 2)
        with patch.object(assistant, "ask", return_value=[]) as ask:
            asyncio.run(assistant.main(options.question, agent, config))
        ask.assert_called_once_with(agent, options.question, config)

    def test_invalid_worker_count_refused_before_model_work(self):
        with self.assertRaises(SystemExit):
            assistant.parse_options(["--workers", "0", "Check rollback"])

    def test_empty_question_refused_before_model_work(self):
        with self.assertRaises(SystemExit):
            assistant.parse_options([])

    def test_recording_requires_explicit_opt_in(self):
        result = subprocess.run([sys.executable, "record.py"], cwd=Path(__file__).parent, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("recording is opt-in", result.stderr)

if __name__ == "__main__":
    unittest.main()
