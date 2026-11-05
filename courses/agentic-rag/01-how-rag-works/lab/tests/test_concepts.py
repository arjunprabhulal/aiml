import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import Mock
from agentic_rag.concepts import ROOT, Reply, SavedEmbeddings, answer, build_index, check_reply, chunks, replay
from exercise import feedback

class ConceptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record=json.loads((ROOT/'runs/2026-10-22-concept/recorded-run.json').read_text())
        cls.index=build_index(cls.record['embeddings'])
    def test_replay_matches_actual_recorded_results(self):
        self.assertEqual(replay(),self.record['results'])
    def test_chunks_keep_their_source_links(self):
        self.assertEqual({d.metadata['id']for d in chunks()},{'path-read','path-write','json-text'})
        self.assertTrue(all(d.metadata['url'].startswith('https://docs.python.org/')for d in chunks()))
    def test_record_matches_the_corpus(self):
        self.assertEqual(hashlib.sha256((ROOT/'data/docs.json').read_bytes()).hexdigest(),self.record['corpus_sha256'])
    def test_saved_embeddings_reject_unrecorded_inputs(self):
        with self.assertRaises(KeyError): SavedEmbeddings(self.record['embeddings']).embed_query('A new question')
    def test_blank_question_is_rejected_before_search(self):
        index=Mock()
        with self.assertRaisesRegex(ValueError,'nonblank'):answer(' ',index,Mock())
        index.similarity_search.assert_not_called()
    def test_no_context_skips_the_model(self):
        index=Mock();index.similarity_search.return_value=[];model=Mock()
        result=answer('Where is the API documented?',index,model)
        self.assertEqual(result['status'],'not_in_docs');self.assertEqual(result['source_links'],[])
        model.assert_not_called()
    def test_unretrieved_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'only source IDs'):
            check_reply(Reply(status='answered',answer='Use another page.',source_ids=['invented-page']),chunks())
    def test_answer_without_a_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'needs a link'):
            check_reply(Reply(status='answered',answer='Use UTF-8.',source_ids=[]),chunks())
    def test_missing_answer_cannot_attach_unrelated_links(self):
        with self.assertRaisesRegex(ValueError,'unrelated source'):
            check_reply(Reply(status='not_in_docs',answer='Not documented.',source_ids=['path-read']),chunks())
    def test_valid_link_does_not_establish_answer_correctness(self):
        check_reply(Reply(status='answered',answer='Path.write_text appends instead of overwriting.',source_ids=['path-write']),chunks())
    def test_unanswerable_record_has_no_source_links(self):
        self.assertEqual(self.record['results'][1]['status'],'not_in_docs')
        self.assertEqual(self.record['results'][1]['source_links'],[])
    def test_exercise_feedback_explains_read_write_confusion(self):
        self.assertFalse(feedback('path-read')[0]);self.assertIn('reads',feedback('path-read')[1])
        self.assertTrue(feedback('path-write')[0])

if __name__=='__main__':unittest.main()


class BaselineExampleTests(unittest.TestCase):
    def test_failed_utf8_case_is_the_preserved_baseline(self):
        from baseline_example import load_case
        case=load_case()
        self.assertEqual(case['context_ids'],['path-read-3-13','path-read'])
        self.assertEqual(case['status'],'not_in_docs')
        self.assertEqual(case['source_links'],[])
        self.assertNotIn('path-write',case['context_ids'])

    def test_changed_baseline_is_refused_without_a_fallback(self):
        from baseline_example import load_case, RECORD
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'changed.json'
            path.write_bytes(RECORD.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'saved baseline bytes changed'):
                load_case(path)
