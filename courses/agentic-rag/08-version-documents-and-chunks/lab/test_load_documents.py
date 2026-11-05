import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from load_documents import IngestionError, MAX_BYTES, load_documents, load_source, read_manifest

class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
    def source(self, raw=b'# Test\n', path='test.md'):
        (self.root / path).write_bytes(raw)
        return dict(source_id='test', path=path, title='Test', sha256=hashlib.sha256(raw).hexdigest())
    def test_manifest_requires_object(self):
        path = self.root / 'manifest.json'; path.write_text('[]')
        with self.assertRaisesRegex(IngestionError, 'invalid_manifest'): read_manifest(path)
    def test_malformed_manifest_is_normalized(self):
        path = self.root / 'manifest.json'; path.write_text('{broken')
        with self.assertRaisesRegex(IngestionError, 'unreadable_manifest'): read_manifest(path)
    def test_missing_manifest_is_normalized(self):
        with self.assertRaisesRegex(IngestionError, 'unreadable_manifest'): read_manifest(self.root / 'missing.json')
    def test_optional_source_metadata_requires_strings(self):
        for key in ('version', 'url', 'fact_status'):
            with self.subTest(key=key):
                source = self.source(); source[key] = []
                path = self.root / 'manifest.json'
                path.write_text(json.dumps(dict(schema_version=1, sources=[source])))
                with self.assertRaisesRegex(IngestionError, 'invalid_manifest'): read_manifest(path)
    def test_directory_rejected_before_read(self):
        source = self.source(); (self.root / 'test.md').unlink(); (self.root / 'test.md').mkdir()
        with self.assertRaisesRegex(IngestionError, 'nonregular_source'): load_source(self.root, source)
    def test_pinned_documents(self):
        result = load_documents(Path(__file__).parent / 'fixtures/initial/source-manifest.json')
        self.assertEqual([d['source_id'] for d in result['documents']], ['path-write', 'path-read', 'json-text', 'path-read-3-13'])
        self.assertIn('write_text', result['documents'][0]['text'])
    def test_missing_file(self):
        source = self.source(); (self.root / 'test.md').unlink()
        with self.assertRaisesRegex(IngestionError, 'unreadable_source'): load_source(self.root, source)
    def test_hash_mismatch(self):
        source = self.source(); (self.root / 'test.md').write_text('changed')
        with self.assertRaisesRegex(IngestionError, 'hash_mismatch'): load_source(self.root, source)
    def test_outside_root(self):
        source = self.source(); source['path'] = '../outside.md'
        with self.assertRaisesRegex(IngestionError, 'invalid_path'): load_source(self.root, source)
    def test_symlink_escape(self):
        source = self.source(); (self.root / 'link.md').symlink_to(self.root / 'test.md'); source['path'] = 'link.md'
        with self.assertRaisesRegex(IngestionError, 'symlink_source'): load_source(self.root, source)
    def test_invalid_utf8(self):
        with self.assertRaisesRegex(IngestionError, 'invalid_utf8'): load_source(self.root, self.source(b'\xff'))
    def test_duplicate_identity(self):
        source = self.source(); manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps(dict(schema_version=1, sources=[source,source])))
        with self.assertRaisesRegex(IngestionError, 'duplicate_identity'): load_documents(manifest)
    def test_size_limit(self):
        with self.assertRaisesRegex(IngestionError, 'size_limit'): load_source(self.root, self.source(b'x' * (MAX_BYTES + 1)))
    def test_empty_text(self):
        with self.assertRaisesRegex(IngestionError, 'invalid_text'): load_source(self.root, self.source(b' \n'))
    def test_newline_normalization_preserves_byte_hash(self):
        source = self.source(b'# Test\r\n'); result = load_source(self.root, source)
        self.assertEqual(result['sha256'], source['sha256']); self.assertEqual(result['text'], '# Test\n')

if __name__ == '__main__': unittest.main()
