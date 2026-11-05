"""Deterministic application checks plus real PostgreSQL adapter behavior."""
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from langchain_core.documents import Document
from pydantic import ValidationError
from sqlalchemy.exc import DataError
from library import answer_question, Answer, Citation, RecordedEmbeddings, check_identity, documents, vector_store, validate_citations
from pg_cluster import Cluster
ROOT = Path(__file__).parent

class CitationTests(unittest.TestCase):
    def setUp(self):
        self.doc = Document(id='deploy#rollback', page_content='Select the previous production digest and create a new deployment.', metadata={'source':'platform/deploy','team':'platform'})
    def answer(self, source='deploy#rollback', quote='Select the previous production digest', **kw):
        return Answer(status='answered', answer=kw.get('text','Select the previous digest.'), citations=[Citation(source_id=source, quote=quote)])
    def test_valid_excerpt_accepts_whitespace_differences(self):
        validate_citations(self.answer(quote='Select  the previous\nproduction digest'), [self.doc])
    def test_unretrieved_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'outside'): validate_citations(self.answer(source='keys#rotate'), [self.doc])
    def test_quote_from_another_chunk_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'contiguous'): validate_citations(self.answer(quote='revoke the old service key'), [self.doc])
    def test_joining_distant_words_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'contiguous'): validate_citations(self.answer(quote='Select the previous new deployment.'), [self.doc])
    def test_answer_without_citations_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'needs'): validate_citations(Answer(status='answered',answer='Use the old digest',citations=[]),[self.doc])
    def test_abstention_cannot_attach_a_citation(self):
        value=self.answer(); value.status='not_in_sources'
        with self.assertRaisesRegex(ValueError,'abstention'): validate_citations(value,[self.doc])
    def test_quote_membership_does_not_establish_entailment(self):
        # Deliberately false claim, real excerpt: this validator cannot grade the claim.
        validate_citations(self.answer(text='Rollback always reverses all database migrations.'),[self.doc])
    def test_model_reply_with_bad_source_is_not_returned_as_an_answer(self):
        raw=SimpleNamespace(usage_metadata={},response_metadata={})
        with patch('library.ChatGoogleGenerativeAI') as adapter:
            adapter.return_value.with_structured_output.return_value.invoke.return_value={
                'parsing_error':None,'parsed':self.answer(source='not-supplied'),'raw':raw}
            with self.assertRaisesRegex(ValueError,'outside'):
                answer_question('How do I roll back?',[self.doc])
    def test_unrecognized_status_is_rejected_by_schema(self):
        with self.assertRaises(ValidationError): Answer(status='probably',answer='maybe',citations=[])

class EmbeddingTests(unittest.TestCase):
    def test_model_digest_change_is_refused(self):
        with self.assertRaisesRegex(ValueError,'identity changed'): check_identity({'digest':'old'},{'digest':'new'})
    def test_chunking_change_is_refused(self):
        with self.assertRaisesRegex(ValueError,'identity changed'): check_identity({'chunk_size':420},{'chunk_size':500})
    def test_recorded_adapter_does_not_invent_an_unknown_query(self):
        with self.assertRaises(KeyError): RecordedEmbeddings({'documents':{},'queries':{}}).embed_query('unknown')
    def test_chunk_ids_are_stable_and_distinct(self):
        one=documents(); two=documents()
        self.assertEqual([d.id for d in one],[d.id for d in two])
        self.assertEqual(len(one),len({d.id for d in one}))

class StoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pg=Cluster().__enter__()
        cls.saved=json.loads((ROOT/'vectors.json').read_text())
        cls.embeddings=RecordedEmbeddings(cls.saved)
        cls.chunks=documents()
    @classmethod
    def tearDownClass(cls): cls.pg.__exit__()
    def store(self, name): return vector_store(self.pg.url,self.embeddings,table=name)
    def test_same_id_upsert_updates_content_and_team(self):
        a,b=self.chunks[0],self.chunks[-1]
        with self.store('upserts') as store:
            store.add_documents([a],ids=[a.id])
            store.add_documents([b],ids=[a.id])
            hits=store.similarity_search('How do I roll back a reporting view?',filter={'team':b.metadata['team']})
            self.assertEqual(len(hits),1); self.assertEqual(hits[0].page_content,b.page_content)
            self.assertEqual(store.similarity_search('How do I roll back a service?',filter={'team':a.metadata['team']}),[])
    def test_delete_removes_every_supplied_chunk_id(self):
        with self.store('deletions') as store:
            store.add_documents(self.chunks,ids=[d.id for d in self.chunks])
            ids=[d.id for d in self.chunks if d.metadata['source']=='platform/deploy']
            self.assertTrue(store.delete(ids=ids))
            hits=store.similarity_search('How do I roll back a service?',k=100)
            self.assertTrue(hits); self.assertFalse(set(ids)&{d.id for d in hits})
    def test_filter_value_is_data_instead_of_sql(self):
        with self.store('filters') as store:
            store.add_documents(self.chunks,ids=[d.id for d in self.chunks])
            self.assertEqual(store.similarity_search('How do I roll back a service?',filter={'team':"platform' OR '1'='1"}),[])
            hits=store.similarity_search('How do I roll back a reporting view?',filter={'team':'data'})
            self.assertTrue(hits); self.assertTrue(all(d.metadata['team']=='data' for d in hits))
    def test_reopening_the_table_retains_documents(self):
        with self.store('reopened') as store: store.add_documents(self.chunks,ids=[d.id for d in self.chunks])
        with vector_store(self.pg.url,self.embeddings,table='reopened',initialize=False) as store:
            self.assertEqual(store.similarity_search('How do I roll back a service?',k=1)[0].metadata['source'],'platform/deploy')
    def test_library_batch_is_not_atomic(self):
        from langchain_core.embeddings import Embeddings
        class BrokenSecondVector(Embeddings):
            def embed_documents(self,texts): return [[1.0,0.0],[1.0,0.0,0.0]]
            def embed_query(self,text): return [1.0,0.0]
        with vector_store(self.pg.url,BrokenSecondVector(),dimensions=2,table='partial_batch') as store:
            with self.assertRaises(DataError) as rejected: store.add_documents(self.chunks[:2],ids=['first','second'])
            self.assertEqual(rejected.exception.orig.sqlstate,'22000')
            hits=store.similarity_search('anything',k=10)
            self.assertEqual([d.id for d in hits],['first'])

if __name__=='__main__': unittest.main(verbosity=2)
