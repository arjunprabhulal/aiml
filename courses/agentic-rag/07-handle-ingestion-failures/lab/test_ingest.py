from pathlib import Path
import tempfile
import json
import subprocess
import sys
import unittest
from ingest import failure_exercise, ingest
from load_documents import IngestionError

MANIFEST = Path(__file__).parent / 'fixtures/source-manifest.json'

class BatchTests(unittest.TestCase):
    def test_exercise_rejects_traversal_before_staging(self):
        data = json.loads(MANIFEST.read_text())
        data['sources'][0]['path'] = '../outside.md'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'; path.write_text(json.dumps(data))
            with self.assertRaisesRegex(IngestionError, 'invalid_path'): failure_exercise(path)
    def test_exercise_requires_four_sources(self):
        data = json.loads(MANIFEST.read_text()); data['sources'] = data['sources'][:1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'; path.write_text(json.dumps(data))
            with self.assertRaisesRegex(IngestionError, 'exercise_requires_four_sources'): failure_exercise(path)
    def test_partial_exit_is_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result.json'
            run = subprocess.run([sys.executable, str(Path(__file__).parent / 'ingest.py'), '--exercise-failures', '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(json.loads(output.read_text())['status'], 'partial')
    def test_complete_batch(self):
        result = ingest(MANIFEST)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['documents']), 4)
        self.assertEqual(result['failures'], [])
    def test_partial_batch_reports_every_rejected_source(self):
        before = MANIFEST.read_bytes()
        result = failure_exercise(MANIFEST)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([d['source_id'] for d in result['documents']], ['path-write'])
        self.assertEqual([f['error'] for f in result['failures']], ['hash_mismatch','unreadable_source','invalid_utf8'])
        self.assertEqual(MANIFEST.read_bytes(), before)
    def test_invalid_manifest_aborts_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'; path.write_text('{"schema_version":1,"sources":[]}')
            with self.assertRaisesRegex(IngestionError, 'invalid_manifest'): ingest(path)
    def test_all_sources_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'; path.write_bytes(MANIFEST.read_bytes())
            result = ingest(path)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(len(result['failures']), 4)

if __name__ == '__main__': unittest.main()
