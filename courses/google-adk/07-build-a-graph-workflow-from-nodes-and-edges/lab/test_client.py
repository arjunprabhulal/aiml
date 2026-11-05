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


from google.adk import Workflow
from google.adk.cli.utils.agent_loader import AgentLoader
from harness import ReplayLlm
import release_notes
import test_release_notes
import graph_client

class PositiveWorkflow(unittest.TestCase):


    def test_direct_positive_client_replays_all_original_node_outputs(self):
        model = test_release_notes.replay()
        rows = asyncio.run(graph_client.run_one(graph_client.parse_options([]), model))
        self.assertEqual(rows["events"], test_release_notes.RECORD["events"])
        self.assertEqual(model.calls, [])

    def test_missing_or_empty_log_is_refused_before_workflow_or_provider(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(graph_client, "build_workflow") as factory:
            path = Path(tmp) / "input.log"
            with self.assertRaises(FileNotFoundError): asyncio.run(graph_client.run_one(graph_client.parse_options(["--input", str(path)])))
            path.write_text("  ")
            with self.assertRaises(ValueError): asyncio.run(graph_client.run_one(graph_client.parse_options(["--input", str(path)])))
            factory.assert_not_called()

if __name__ == "__main__": unittest.main()
