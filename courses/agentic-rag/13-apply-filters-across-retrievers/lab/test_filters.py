import copy
import unittest
from vector_retriever import VectorRetriever,load_inputs,version_filter
from filtered_retrievers import LexicalRetriever,candidates


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.snapshot,embeddings,self.cases=load_inputs()
        self.vector=VectorRetriever(self.snapshot,embeddings);self.lexical=LexicalRetriever(self.snapshot)
        self.addCleanup(self.lexical.close)

    def test_same_exact_candidate_sets(self):
        for version in ['3.12','3.13','9.99']:
            policy={'version':{'$eq':version}}
            expected=sorted(r['chunk_id'] for r in self.vector.rows if r['version']==version)
            self.assertEqual(candidates(self.vector.rows,policy),expected)
            self.assertEqual(candidates(self.lexical.rows,policy),expected)

    def test_excluded_versions_never_return_from_either_retriever(self):
        policy={'version':{'$eq':'3.13'}}
        for rows in [self.vector.search(self.cases[0]['input'],k=10,policy=policy),self.lexical.search('encoding',k=10,policy=policy)]:
            self.assertTrue(rows);self.assertTrue(all(r['version']=='3.13' for r in rows))

    def test_prefilter_avoids_post_top1_underfill(self):
        policy={'version':{'$eq':'3.13'}}
        for retriever,query in [(self.vector,self.cases[1]['input']),(self.lexical,'encoding')]:
            raw=retriever.search(query,k=1)
            self.assertEqual([r for r in raw if r['version']=='3.13'],[])
            filtered=retriever.search(query,k=1,policy=policy)
            self.assertEqual(len(filtered),1);self.assertEqual(filtered[0]['version'],'3.13')

    def test_unknown_version_is_empty(self):
        policy={'version':{'$eq':'9.99'}}
        self.assertEqual(self.vector.search(self.cases[0]['input'],policy=policy),[])
        self.assertEqual(self.lexical.search('encoding',policy=policy),[])

    def test_empty_filter_means_all_candidates(self):
        self.assertEqual(candidates(self.vector.rows,{}),candidates(self.vector.rows,None))
        self.assertEqual(self.vector.search(self.cases[0]['input'],policy={}),self.vector.search(self.cases[0]['input']))
        self.assertEqual(self.lexical.search('encoding',policy={}),self.lexical.search('encoding'))

    def test_invalid_operator_field_and_type_are_refused(self):
        for policy in [{'version':{'$ne':'3.12'}},{'tenant':{'$eq':'x'}},{'version':3.12},{'version':{'$eq':3.12}},[],{'version':{'$eq':'3.12','extra':1}},{'version':{'$eq':'3.12 OR 1=1'}}]:
            for retriever,query in [(self.vector,self.cases[0]['input']),(self.lexical,'encoding')]:
                with self.subTest(policy=policy),self.assertRaises(ValueError):retriever.search(query,policy=policy)

    def test_invalid_source_metadata_is_refused(self):
        for value in [None,3.12,'3.12 OR 1=1']:
            snapshot=copy.deepcopy(self.snapshot);snapshot['documents'][0]['version']=value
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'invalid_snapshot'):LexicalRetriever(snapshot)

    def test_invalid_lexical_query_and_k_are_refused(self):
        for query in ['', 'encoding OR file','"','x'*65]:
            with self.subTest(query=query),self.assertRaises(ValueError):self.lexical.search(query)
        for k in [0,True,-1]:
            with self.subTest(k=k),self.assertRaises(ValueError):self.lexical.search('encoding',k=k)

    def test_reserved_lexical_words_are_literal_terms(self):
        for query in ['OR','NOT','AND']:
            self.assertEqual(self.lexical.search(query),self.lexical.search(query.lower()))
            self.assertTrue(all(query.lower() in row['text'].lower().split() for row in self.lexical.search(query)))

    def test_unknown_query_is_refused_even_with_no_candidates(self):
        with self.assertRaisesRegex(ValueError,'unrecorded_development_query'):
            self.vector.search('unknown',policy={'version':{'$eq':'9.99'}})

if __name__=='__main__':unittest.main()
