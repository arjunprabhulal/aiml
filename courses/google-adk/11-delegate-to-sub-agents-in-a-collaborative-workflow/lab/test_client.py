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


from google.adk.cli.utils.agent_loader import AgentLoader
import review_client
from test_review_team import RECORD,replay,canonical

class ChosenDiff(unittest.TestCase):
    def test_client_keeps_both_specialist_returns_and_original_event_results(self):
        result=asyncio.run(review_client.run_one(review_client.parse_options([]),replay()))
        self.assertEqual(canonical(result["events"]),canonical(RECORD["events"]))
        self.assertEqual(result["delegations"],["pr_summarizer","style_checker"])



    def test_missing_or_empty_diff_refused_before_factory(self):
        with tempfile.TemporaryDirectory()as tmp,patch.object(review_client,"build_team")as factory:
            path=Path(tmp)/"input.diff"
            with self.assertRaises(FileNotFoundError):asyncio.run(review_client.run_one(review_client.parse_options(["--diff",str(path)])))
            path.write_text(" ")
            with self.assertRaises(ValueError):asyncio.run(review_client.run_one(review_client.parse_options(["--diff",str(path)])))
            factory.assert_not_called()

if __name__=="__main__":unittest.main()
