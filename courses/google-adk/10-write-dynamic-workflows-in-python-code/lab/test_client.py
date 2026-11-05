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
import lint_client
from test_lint_changed import RECORD

class SelectedPages(unittest.TestCase):
    def test_client_keeps_exact_recorded_dynamic_paths_outputs_and_fixtures(self):
        paths = list((HERE / "docs").glob("*.md")); before={p:p.read_bytes() for p in paths}
        model=ReplayLlm(model=RECORD["environment"]["model"],calls=copy.deepcopy(RECORD["model_calls"]))
        result=asyncio.run(lint_client.run_one(lint_client.parse_options([]),model))
        canonical=lambda rows:sorted(json.dumps(x,sort_keys=True)for x in rows)
        self.assertEqual(canonical(result["events"]),canonical(RECORD["events"]))
        self.assertEqual(model.calls,[]);self.assertEqual(before,{p:p.read_bytes()for p in paths})

    def test_missing_outside_or_whitespace_path_refused_before_provider_setup(self):
        with patch.object(lint_client,"build_workflow")as factory:
            for bad in ["../requirements.txt","missing.md","/etc/passwd","install.md cli.md"]:
                with self.assertRaises(SystemExit):lint_client.parse_options([bad])
            factory.assert_not_called()


    def test_chosen_subset_preserves_core_retry_and_loop_constants(self):
        import lint_changed
        args=lint_client.parse_options(["cli.md"])
        self.assertEqual(args.pages,["cli.md"])
        self.assertEqual(lint_changed.MAX_ROUNDS,2);self.assertEqual(lint_changed.MAX_CONCURRENT_PAGES,4)
        fixer=lint_changed.make_fixer()
        self.assertEqual(fixer.retry_config.max_attempts,3);self.assertEqual(fixer.timeout,60)

if __name__=="__main__":unittest.main()
