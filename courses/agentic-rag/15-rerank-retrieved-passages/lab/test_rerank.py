import copy
import unittest
from vector_retriever import load_inputs
from hybrid import HybridRetriever
from rerank import query_tokens,rerank


class RerankTests(unittest.TestCase):
    def setUp(self):
        self.snapshot,embeddings,self.cases=load_inputs()
        self.retriever=HybridRetriever(self.snapshot,embeddings)
        self.query=self.cases[0]['input']
        self.candidates=self.retriever.search(self.query,k=3,candidate_budget=3,policy={'version':{'$eq':'3.12'}})['results']

    def tearDown(self):self.retriever.close()

    def test_candidate_only_preserves_payload_and_original_scores(self):
        before=copy.deepcopy(self.candidates);rows=rerank(self.query,self.candidates,self.snapshot,k=3)
        self.assertEqual(self.candidates,before)
        self.assertEqual({r['chunk_id'] for r in rows},{r['chunk_id'] for r in before})
        for row in rows:
            original=before[row['incoming_rank']-1]
            for key,value in original.items():self.assertEqual(row[key],value)

    def test_coverage_features_are_exact_and_do_not_read_labels(self):
        rows=rerank(self.query,self.candidates,self.snapshot,k=3)
        changed=[{**r,'expected_target':'irrelevant-label'} for r in self.candidates]
        self.assertEqual([r['chunk_id'] for r in rows],[r['chunk_id'] for r in rerank(self.query,changed,self.snapshot,k=3)])
        for row in rows:
            features=row['rerank_features']
            self.assertEqual(row['coverage_score'],features['matched_count']/features['query_token_count'])
            self.assertEqual(features['query_tokens'],query_tokens(self.query))

    def test_equal_coverage_preserves_incoming_order(self):
        rows=rerank('zzunmatched',list(reversed(self.candidates)),self.snapshot,k=3)
        self.assertEqual([r['chunk_id'] for r in rows],[r['chunk_id'] for r in reversed(self.candidates)])

    def test_empty_candidates_return_empty(self):self.assertEqual(rerank(self.query,[],self.snapshot),[])

    def test_invalid_query_and_k_are_rejected(self):
        for query in ['',None,'!!!','a'*513,' '.join(['x']*33)]:
            with self.subTest(query=query),self.assertRaises(ValueError):rerank(query,self.candidates,self.snapshot)
        for k in [0,True,1.1]:
            with self.subTest(k=k),self.assertRaises(ValueError):rerank(self.query,self.candidates,self.snapshot,k=k)

    def test_new_duplicate_or_altered_candidates_are_rejected(self):
        for change in ['new','duplicate','text','version','score']:
            rows=copy.deepcopy(self.candidates)
            if change=='new':rows[0]['chunk_id']='new'
            elif change=='duplicate':rows.append(rows[0])
            elif change=='score':rows[0]['fused_score']=float('nan')
            else:rows[0][change]='altered'
            with self.subTest(change=change),self.assertRaises(ValueError):rerank(self.query,rows,self.snapshot)

    def test_unknown_vector_query_is_rejected_before_reranking(self):
        with self.assertRaisesRegex(ValueError,'unrecorded'):self.retriever.search('unknown developer question')

    def test_unhashable_ids_huge_scores_and_invalid_ranks_are_rejected(self):
        for key,value in [('chunk_id',[]),('fused_score',10**1000),('lexical_rank',True),('vector_contribution',float('inf'))]:
            rows=copy.deepcopy(self.candidates);rows[0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):rerank(self.query,rows,self.snapshot)

    def test_controlled_reversed_candidate_order_is_reranked_by_coverage(self):
        query=self.cases[1]['input']
        original=self.retriever.search(query,k=3,candidate_budget=3,policy={'version':{'$eq':'3.12'}})['results']
        reversed_candidates=list(reversed(original))
        rows=rerank(query,reversed_candidates,self.snapshot,k=3)
        self.assertNotEqual(rows[0]['chunk_id'],reversed_candidates[0]['chunk_id'])
        self.assertEqual(rows[0]['source_id'],'path-write')
        self.assertEqual({r['chunk_id'] for r in rows},{r['chunk_id'] for r in original})

if __name__=='__main__':unittest.main()
