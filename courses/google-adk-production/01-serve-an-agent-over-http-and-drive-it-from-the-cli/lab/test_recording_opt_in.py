"""The ordinary recorder invocation must not launch services or overwrite records."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import unittest
class RecordingOptIn(unittest.TestCase):
    def test_public_record_omits_opaque_signatures_without_changing_semantic_fields(self):
        import record
        value = {"content": {"parts": [{"text": "answer", "thoughtSignature": "opaque"}]},
                 "usageMetadata": {"totalTokenCount": 7}, "thought_signature": "opaque"}
        self.assertEqual(record.public_projection(value),
                         {"content": {"parts": [{"text": "answer"}]}, "usageMetadata": {"totalTokenCount": 7}})
        saved = json.loads(Path("recorded-runs.json").read_text())
        self.assertEqual(saved, record.public_projection(saved))

    def test_recorder_refuses_without_explicit_permission(self):
        paths = [Path(x) for x in ["recorded-runs.json", "run-output.txt", "test-output.txt"]]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        result = subprocess.run([sys.executable, "record.py"], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("recording is opt-in", result.stderr)
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
if __name__ == "__main__":
    unittest.main()
