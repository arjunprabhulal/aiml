import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from conflicts import DirectiveError,GateError,claims_from_source,gate,digest
from load_documents import IngestionError,load_documents

ROOT=Path(__file__).parent
MANIFEST=ROOT/'fixtures/source-manifest.json'


class ConflictTests(unittest.TestCase):
    def test_exact_version_excludes_newer_incompatible_rule(self):
        result=gate(MANIFEST,['quill-guide','quill-new-version'],'1.0')
        self.assertEqual(result['status'],'ready');self.assertEqual(result['agreed_value'],'refuse')
        self.assertEqual(result['excluded_wrong_version_ids'],['quill-new-version'])
        self.assertEqual([c['source_id'] for c in result['claims']],['quill-guide'])

    def test_agreement_prepares_request_with_all_quotes_without_model_answer(self):
        result=gate(MANIFEST,['quill-guide','quill-reference'],'1.0')
        self.assertEqual(result['status'],'ready');self.assertIsNotNone(result['answer_request'])
        payload=json.loads(result['answer_request']['messages'][1]['content'])
        self.assertEqual(payload['source_claims'],result['claims']);self.assertEqual(len(result['claims']),2)
        self.assertNotIn('answer',result)

    def test_same_version_conflict_withholds_request_and_retains_all_claims(self):
        ids=['quill-guide','quill-conflicting-guide']
        for order in [ids,list(reversed(ids))]:
            result=gate(MANIFEST,order,'1.0')
            self.assertEqual(result['status'],'conflict');self.assertIsNone(result['answer_request'])
            self.assertEqual({c['source_id'] for c in result['claims']},set(ids))
            self.assertEqual({c['value'] for c in result['claims']},{'refuse','overwrite'})
            self.assertNotIn('agreed_value',result)

    def test_absent_version_empty_candidates_and_missing_claim_do_not_fallback(self):
        for ids,version,key in [(['quill-guide','quill-new-version'],'3.0','existing_path'),([], '1.0','existing_path'),(['quill-guide'],'1.0','close_required'),(['quill-guide','quill-missing-claim'],'1.0','existing_path')]:
            result=gate(MANIFEST,ids,version,key)
            self.assertEqual(result['status'],'not_in_docs');self.assertIsNone(result['answer_request'])

    def test_unknown_value_and_malformed_directive_refuse(self):
        for sid,message in [('quill-unknown-value','unknown_directive_value'),('quill-malformed','malformed_directive')]:
            with self.subTest(sid=sid),self.assertRaisesRegex(DirectiveError,message):gate(MANIFEST,[sid],'1.0')
        # The invalid value is not parsed when its declared version is ineligible.
        result=gate(MANIFEST,['quill-unknown-value','quill-new-version'],'2.0')
        self.assertEqual(result['status'],'ready');self.assertEqual(result['agreed_value'],'overwrite')

    def test_duplicate_unknown_operation_key_and_prefix_fail_closed(self):
        original=load_documents(MANIFEST)['documents'][0]
        for text,message in [('@quill create_copy existing_path=refuse\n@quill create_copy existing_path=refuse\n','duplicate_directive'),('@quill save_copy existing_path=refuse\n','unsupported_operation'),('@quill create_copy surprise=refuse\n','unsupported_claim_key'),('@other create_copy existing_path=refuse\n','malformed_directive'),(' @quill create_copy existing_path=refuse\n','malformed_directive')]:
            with self.subTest(text=text),self.assertRaisesRegex(DirectiveError,message):claims_from_source({**original,'text':text})

    def test_claim_quotes_offsets_lines_and_revision_bind_exact_source(self):
        sources={s['source_id']:s for s in load_documents(MANIFEST)['documents']}
        result=gate(MANIFEST,['quill-guide','quill-reference'],'1.0')
        for claim in result['claims']:
            source=sources[claim['source_id']]
            self.assertEqual(source['text'][claim['start']:claim['end']],claim['quote'])
            self.assertEqual(source['text'].splitlines()[claim['start_line']-1],claim['quote'])
            self.assertEqual(claim['source_sha256'],source['sha256'])
            self.assertEqual(claim['document_revision'],digest({key:value for key,value in source.items() if key!='text'}))

    def test_changed_pinned_source_is_refused_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'fixtures';shutil.copytree(ROOT/'fixtures',root)
            with (root/'docs/quill-guide.md').open('a') as stream:stream.write('\nChanged rule.\n')
            with self.assertRaisesRegex(IngestionError,'hash_mismatch'):gate(root/'source-manifest.json',['quill-guide'],'1.0')

    def test_invalid_controlled_input_is_refused(self):
        for ids,version,key in [(['unknown'],'1.0','existing_path'),(['quill-guide']*2,'1.0','existing_path'),([[]],'1.0','existing_path'),(['quill-guide'],1.0,'existing_path'),(['quill-guide'],'latest','existing_path'),(['quill-guide'],'1.0','unknown')]:
            with self.subTest(ids=ids,version=version),self.assertRaises(GateError):gate(MANIFEST,ids,version,key)

    def test_partial_missing_eligible_claim_withholds_request(self):
        result=gate(MANIFEST,['quill-guide','quill-missing-claim'],'1.0')
        self.assertEqual(result['status'],'not_in_docs')
        self.assertIsNone(result['answer_request'])
        self.assertEqual(result['missing_claim_source_ids'],['quill-missing-claim'])

    def test_missing_version_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'fixtures';shutil.copytree(ROOT/'fixtures',root)
            manifest=json.loads((root/'source-manifest.json').read_text())
            del manifest['sources'][0]['version']
            (root/'source-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(GateError,'invalid_source_version'):gate(root/'source-manifest.json',['quill-guide'],'1.0')

if __name__=='__main__':unittest.main()
