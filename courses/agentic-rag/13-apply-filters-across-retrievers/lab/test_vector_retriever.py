import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from vector_retriever import DIMENSION,SavedEmbeddings,VectorRetriever,checked_vector,load_inputs


class VectorTests(unittest.TestCase):
    def setUp(self):self.snapshot,self.embeddings,self.cases=load_inputs()

    def test_real_store_returns_known_chunk_ids(self):
        retriever=VectorRetriever(self.snapshot,self.embeddings)
        rows=retriever.search(self.cases[0]['input'],k=2)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['source_id'],'path-read-3-13')
        self.assertTrue(all(r['chunk_id'] in {c['chunk_id'] for d in self.snapshot['documents'] for c in d['chunks']} for r in rows))
        self.assertTrue(all(math.isfinite(r['score']) for r in rows))

    def test_unknown_query_is_refused(self):
        with self.assertRaisesRegex(ValueError,'unrecorded_development_query'):self.embeddings.embed_query('unknown')

    def test_preserved_held_out_queries_are_not_exposed(self):
        raw=json.loads((Path(__file__).parent/'fixtures/vectors.json').read_text())
        held=[q for q in raw['questions'] if q not in self.embeddings.questions]
        self.assertTrue(held)
        for question in held:
            with self.subTest(question=question),self.assertRaisesRegex(ValueError,'unrecorded'):self.embeddings.embed_query(question)

    def test_unknown_document_is_refused(self):
        with self.assertRaisesRegex(ValueError,'unrecorded_document'):self.embeddings.embed_documents(['unknown'])

    def test_changed_corpus_text_is_refused(self):
        changed=copy.deepcopy(self.snapshot);changed['documents'][0]['chunks'][0]['text']+=' altered'
        with self.assertRaisesRegex(ValueError,'invalid_snapshot'):VectorRetriever(changed,self.embeddings)

    def test_recorded_file_tampering_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'vectors.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'recording_hash'):load_inputs(root)

    def test_invalid_dimensions_values_and_norm_are_refused(self):
        fixtures=[[],[1.0]*(DIMENSION-1),[0.0]*DIMENSION,[math.nan]*DIMENSION,[math.inf]*DIMENSION,[True]*DIMENSION]
        for vector in fixtures:
            with self.subTest(vector=vector[:1]),self.assertRaises(ValueError):checked_vector(vector)

    def test_embedding_results_do_not_mutate_saved_vectors(self):
        query=self.cases[0]['input'];first=self.embeddings.embed_query(query);expected=first[0]
        first[0]=123
        self.assertEqual(self.embeddings.embed_query(query)[0],expected)

    def test_invalid_k_is_refused(self):
        retriever=VectorRetriever(self.snapshot,self.embeddings)
        for k in [0,-1,True,1.5]:
            with self.subTest(k=k),self.assertRaisesRegex(ValueError,'invalid_k'):retriever.search(self.cases[0]['input'],k=k)

    def test_unanswerable_development_question_still_returns_candidates(self):
        case=next(c for c in self.cases if c['id']=='backup-schedule')
        self.assertEqual(case['class'],'unsupported')
        self.assertTrue(VectorRetriever(self.snapshot,self.embeddings).search(case['input']))

    def test_equal_score_ties_use_chunk_id(self):
        # Synthetic unit vectors isolate ties; they are not model execution proof.
        vector=[1.0]+[0.0]*(DIMENSION-1)
        recording={'documents':{c['text']:vector for d in self.snapshot['documents'] for c in d['chunks']},'questions':{self.cases[0]['input']:vector}}
        embeddings=SavedEmbeddings(recording,[self.cases[0]['input']])
        rows=VectorRetriever(self.snapshot,embeddings).search(self.cases[0]['input'],k=4)
        self.assertEqual([r['chunk_id'] for r in rows],sorted(r['chunk_id'] for r in rows))

    def test_changed_chunk_identity_is_refused(self):
        changed=copy.deepcopy(self.snapshot);changed['documents'][0]['chunks'][0]['chunk_id']='altered'
        with self.assertRaisesRegex(ValueError,'invalid_snapshot'):VectorRetriever(changed,self.embeddings)

if __name__=='__main__':unittest.main()
