"""Tests exercise binding and verification against actual temporary files."""
from dataclasses import replace
from pathlib import Path
import os
import tempfile
import unittest

from sources import MAX_BYTES, SourceError, bind_passage, verify_passage


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "guide.md").write_bytes(b"# Guide\r\n\r\nRun tests.\r\nDeploy.\r\n")

    def test_preserves_exact_line_endings_and_inclusive_span(self):
        passage = bind_passage(self.root, "guide.md", 3, 4)
        self.assertEqual(verify_passage(self.root, passage), "Run tests.\r\nDeploy.\r\n")

    def test_stable_identity_and_distinct_spans(self):
        first = bind_passage(self.root, "guide.md", 3, 3)
        self.assertEqual(first, bind_passage(self.root, "guide.md", 3, 3))
        self.assertNotEqual(first.chunk_id, bind_passage(self.root, "guide.md", 3, 4).chunk_id)

    def test_changed_file_invalidates_old_passage(self):
        passage = bind_passage(self.root, "guide.md", 3, 3)
        with (self.root / "guide.md").open("ab") as stream:
            stream.write(b"New instruction.\n")
        with self.assertRaisesRegex(SourceError, "current source snapshot"):
            verify_passage(self.root, passage)

    def test_tampered_text_hash_id_and_span_are_rejected(self):
        passage = bind_passage(self.root, "guide.md", 3, 3)
        for change in ({"text": "Deploy."}, {"source_sha256": "0" * 64},
                       {"chunk_id": "0" * 64}, {"end_line": 4}):
            with self.subTest(change=change), self.assertRaises(SourceError):
                verify_passage(self.root, replace(passage, **change))

    def test_invalid_spans_are_rejected(self):
        for start, end in [(0, 1), (3, 2), (1, 5), (True, 1), (1, 1.0)]:
            with self.subTest(span=(start, end)), self.assertRaises(SourceError):
                bind_passage(self.root, "guide.md", start, end)

    def test_blank_passage_is_rejected(self):
        with self.assertRaisesRegex(SourceError, "non-whitespace"):
            bind_passage(self.root, "guide.md", 2, 2)

    def test_unsafe_and_missing_paths_are_rejected(self):
        for path in ["../guide.md", "/guide.md", "./guide.md", "", "missing.md"]:
            with self.subTest(path=path), self.assertRaises(SourceError):
                bind_passage(self.root, path, 1, 1)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.md"
            target.write_text("Outside\n")
            (self.root / "link.md").symlink_to(target)
            with self.assertRaisesRegex(SourceError, "escapes"):
                bind_passage(self.root, "link.md", 1, 1)

    def test_oversized_source_is_rejected(self):
        (self.root / "large.md").write_bytes(b"x" * (MAX_BYTES + 1))
        with self.assertRaisesRegex(SourceError, "MAX_BYTES"):
            bind_passage(self.root, "large.md", 1, 1)

    def test_exact_byte_limit_is_accepted(self):
        (self.root / "limit.md").write_bytes(b"x" * MAX_BYTES)
        self.assertEqual(len(bind_passage(self.root, "limit.md", 1, 1).text), MAX_BYTES)

    def test_nonregular_sources_are_rejected(self):
        (self.root / "directory").mkdir()
        os.mkfifo(self.root / "pipe")
        for path in ["directory", "pipe"]:
            with self.subTest(path=path), self.assertRaisesRegex(SourceError, "regular file"):
                bind_passage(self.root, path, 1, 1)

    def test_non_utf8_is_rejected(self):
        (self.root / "binary.md").write_bytes(b"\xff")
        with self.assertRaisesRegex(SourceError, "UTF-8"):
            bind_passage(self.root, "binary.md", 1, 1)


if __name__ == "__main__":
    unittest.main()
