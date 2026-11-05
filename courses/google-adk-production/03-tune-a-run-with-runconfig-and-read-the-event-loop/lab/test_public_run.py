"""Verify the public fresh-run inventory; outcome tests live in the lab's replay suite."""
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
RUN = HERE / "runs/docuctl-2026-10-25/provenance.json"
OPAQUE = {"thought_signature", "thoughtSignature", "function_call_signature", "functionCallSignature"}


def keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from keys(child)


class PublicRecordedRun(unittest.TestCase):
    def test_selected_output_hashes(self):
        proof = json.loads(RUN.read_text())
        self.assertTrue(proof["output_files_sha256"])
        for name, digest in proof["output_files_sha256"].items():
            self.assertEqual(hashlib.sha256((HERE / name).read_bytes()).hexdigest(), digest, name)

    def test_provider_attempts_are_bounded_and_receipted(self):
        proof = json.loads(RUN.read_text())
        self.assertEqual(proof["model"], "gemini-3.8-flash")
        attempts = proof["provider_attempts"]
        self.assertTrue(attempts)
        self.assertEqual(len({item["attempt"] for item in attempts}), len(attempts))
        for item in attempts:
            self.assertGreater(item["max_output_tokens"], 0)
            self.assertLessEqual(item["max_output_tokens"], 8192)
            self.assertRegex(item["request_sha256"], r"^[a-f0-9]{64}$")
            self.assertRegex(item["private_request_receipt_sha256"], r"^[a-f0-9]{64}$")
            if item["http_status"] == 200:
                self.assertRegex(item["private_response_sha256"], r"^[a-f0-9]{64}$")

    def test_public_files_exclude_opaque_fields_and_sqlite(self):
        for path in HERE.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            self.assertFalse(path.read_bytes().startswith(b"SQLite format 3\x00"), str(path))
            self.assertNotEqual(path.suffix, ".db", str(path))
            if path.suffix not in {".json", ".jsonl"}:
                continue
            values = [json.loads(line) for line in path.read_text().splitlines() if line] if path.suffix == ".jsonl" else [json.loads(path.read_text())]
            for value in values:
                self.assertFalse(OPAQUE.intersection(keys(value)), str(path))


if __name__ == "__main__":
    unittest.main()
