import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from load_documents import IngestionError
from version_documents import CHUNKER, build_snapshot, canonical_hash, compare, paragraphs, validate_snapshot, snapshot_identity

ROOT = Path(__file__).parent

class VersionTests(unittest.TestCase):
    def snapshot(self, variant='initial'):
        return build_snapshot(ROOT / 'fixtures' / variant / 'source-manifest.json')
    def test_valid_snapshot_round_trip(self):
        snapshot = self.snapshot()
        self.assertEqual(validate_snapshot(json.loads(json.dumps(snapshot))), snapshot)
    def test_tampered_text_same_id_is_refused(self):
        snapshot = self.snapshot(); snapshot['documents'][0]['text'] += 'changed'
        with self.assertRaisesRegex(IngestionError, 'invalid_snapshot'): validate_snapshot(snapshot)
    def test_tampered_chunk_same_id_is_refused(self):
        snapshot = self.snapshot(); snapshot['documents'][0]['chunks'][0]['text'] += 'changed'
        with self.assertRaisesRegex(IngestionError, 'invalid_snapshot'): validate_snapshot(snapshot)
    def test_tampered_config_same_id_is_refused(self):
        snapshot = self.snapshot(); snapshot['chunker']['version'] = 2
        with self.assertRaisesRegex(IngestionError, 'invalid_snapshot'): validate_snapshot(snapshot)
    def test_tampered_metadata_same_id_is_refused(self):
        snapshot = self.snapshot(); snapshot['documents'][0]['title'] += 'changed'
        with self.assertRaisesRegex(IngestionError, 'invalid_snapshot'): validate_snapshot(snapshot)
    def test_rehashed_inconsistent_chunk_is_refused(self):
        snapshot = self.snapshot(); snapshot['documents'][0]['chunks'][0]['text'] += 'changed'
        snapshot['snapshot_id'] = snapshot_identity(snapshot['documents'], snapshot['chunker'])
        with self.assertRaisesRegex(IngestionError, 'invalid_snapshot'): validate_snapshot(snapshot)
    def test_rederived_changed_text_retaining_snapshot_id_is_refused(self):
        from version_documents import version_document
        snapshot = self.snapshot(); document = snapshot['documents'][0]
        original = {key:document[key] for key in ('source_id','path','title','sha256','version','url','fact_status','text')}
        original['text'] += 'changed'
        snapshot['documents'][0] = version_document(original, CHUNKER)
        with self.assertRaisesRegex(IngestionError, 'invalid_snapshot'): validate_snapshot(snapshot)
    def test_repeat_run_is_identical(self):
        self.assertEqual(self.snapshot(), self.snapshot())
    def test_paragraph_spans_reconstruct_exact_content(self):
        text = 'first line\nsecond line\n\n  \nthird line\n'
        spans = list(paragraphs(text))
        self.assertEqual(spans, [(1,2,'first line\nsecond line\n'), (5,5,'third line\n')])
        for start, end, passage in spans:
            self.assertEqual(passage, ''.join(text.splitlines(keepends=True)[start-1:end]))
    def test_changed_text_replaces_only_its_document(self):
        before = self.snapshot(); after = self.snapshot('text-change')
        changes = compare(before, after)
        self.assertTrue(changes['snapshot_changed'])
        self.assertEqual([d['source_id'] for d in changes['changed']], ['path-write'])
        self.assertTrue(changes['changed'][0]['raw_bytes_changed'])
        self.assertTrue(changes['changed'][0]['chunk_ids_changed'])
        self.assertEqual(len(next(d for d in after['documents'] if d['source_id']=='path-write')['chunks']), 2)
    def test_metadata_only_change_invalidates_revision_and_chunks(self):
        change = compare(self.snapshot(), self.snapshot('metadata-change'))['changed']
        self.assertEqual(change, [{'source_id':'path-write','raw_bytes_changed':False,'metadata_changed':True,'chunk_ids_changed':True}])
    def test_api_version_is_distinct_from_content_revision(self):
        before = self.snapshot(); after = self.snapshot('text-change')
        old = next(d for d in before['documents'] if d['source_id']=='path-write')
        new = next(d for d in after['documents'] if d['source_id']=='path-write')
        self.assertEqual(old['version'], new['version'])
        self.assertEqual(old['source_id'], new['source_id'])
        self.assertNotEqual(old['document_revision'], new['document_revision'])
    def test_chunk_hash_binds_content_span_and_chunker(self):
        snapshot = self.snapshot(); chunk = snapshot['documents'][0]['chunks'][0]
        identity = {key:chunk[key] for key in ('document_revision','start_line','end_line','text_sha256')}
        identity['chunker'] = snapshot['chunker']
        self.assertEqual(chunk['text_sha256'], hashlib.sha256(chunk['text'].encode()).hexdigest())
        self.assertEqual(chunk['chunk_id'], canonical_hash(identity))
        for key, value in [('start_line',999),('text_sha256','changed'),('chunker',dict(CHUNKER,version=2))]:
            modified = copy.deepcopy(identity);modified[key]=value
            self.assertNotEqual(chunk['chunk_id'], canonical_hash(modified))
    def test_unknown_chunker_is_rejected(self):
        with self.assertRaisesRegex(IngestionError,'unsupported_chunker'):
            build_snapshot(ROOT/'fixtures/initial/source-manifest.json', dict(CHUNKER,version=2))
    def test_manifest_order_does_not_change_snapshot(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'fixtures';shutil.copytree(ROOT/'fixtures/initial',target)
            manifest=target/'source-manifest.json';data=json.loads(manifest.read_text());data['sources'].reverse();manifest.write_text(json.dumps(data))
            self.assertEqual(self.snapshot(),build_snapshot(manifest))
    def test_unpinned_byte_change_is_rejected(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'fixtures';shutil.copytree(ROOT/'fixtures/initial',target)
            (target/'docs/path-write.md').write_text('unreviewed change')
            with self.assertRaisesRegex(IngestionError,'hash_mismatch'):build_snapshot(target/'source-manifest.json')

if __name__ == '__main__': unittest.main()
