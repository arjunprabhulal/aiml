import copy
import math
import unittest
from hybrid import HybridRetriever,QuestionLexicalRetriever,question_terms,reciprocal_rank_fusion
from vector_retriever import load_inputs

class HybridTests(unittest.TestCase):
    def setUp(self):
        self.snapshot,self.embeddings,self.cases=load_inputs()
        self.retriever=HybridRetriever(self.snapshot,self.embeddings);self.addCleanup(self.retriever.close)
        self.query=self.cases[0]['input']
    def row(self,key,score=0.5,lexical=False):
        return dict(chunk_id=key,source_id=key,version='3.12',url='https://example.invalid',text='Controlled fusion unit fixture',**{'native_score' if lexical else 'score':score})
    def test_rank_fusion_uses_one_based_ranks_not_native_scores(self):
        a=self.row('a',-1000,True);b=self.row('b',-0.01,True)
        rows=reciprocal_rank_fusion([a,b],[self.row('b',0.001),self.row('a',0.999)],2,60)
        self.assertEqual([row['chunk_id'] for row in rows],['a','b'])
        for row in rows:self.assertAlmostEqual(row['fused_score'],1/61+1/62)
        self.assertEqual(rows[0]['lexical_score'],-1000)
        self.assertEqual(rows[0]['vector_rank'],2)
    def test_absent_branch_contributes_zero(self):
        row=reciprocal_rank_fusion([self.row('a',-1,True)],[],1,60)[0]
        self.assertEqual(row['vector_contribution'],0)
        self.assertIsNone(row['vector_rank']);self.assertIsNone(row['vector_score'])
        self.assertAlmostEqual(row['fused_score'],1/61)
    def test_duplicate_branch_ids_are_rejected(self):
        row=self.row('a',-1,True)
        with self.assertRaisesRegex(ValueError,'duplicate_branch_chunk_id'):reciprocal_rank_fusion([row,row],[])
    def test_shared_chunk_payload_must_agree(self):
        for field in ['source_id','version','text','url']:
            left=self.row('a',-1,True);right=self.row('a');right[field]='changed'
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError,'inconsistent_chunk_payload'):reciprocal_rank_fusion([left],[right])
    def test_nonfinite_native_scores_rejected(self):
        for score in [float('nan'),float('inf'),True,'1',10**1000]:
            with self.assertRaisesRegex(ValueError,'invalid_native_score'):reciprocal_rank_fusion([],[self.row('a',score)])
    def test_bounds_reject_bool_nonfinite_and_invalid_values(self):
        for key,values in [('k',[True,0,101,1.5]),('candidate_budget',[True,0,101,1.5]),('rank_constant',[True,0,-1,float('inf'),1.5])]:
            for value in values:
                with self.subTest(key=key,value=value):
                    with self.assertRaises(ValueError):self.retriever.search(self.query,**{key:value})
        with self.assertRaisesRegex(ValueError,'candidate_budget_below_k'):self.retriever.search(self.query,k=3,candidate_budget=2)
    def test_question_tokenization_is_bounded_literal_or(self):
        self.assertEqual(question_terms('Path.read_text OR "text"'),['path','read','text','or'])
        for query in ['',None,'!!!','a'*65,' '.join(['word']*33),'x'*513]:
            with self.assertRaisesRegex(ValueError,'invalid_query'):question_terms(query)
        self.assertEqual(self.retriever.lexical.search('text OR "newline"',3),self.retriever.lexical.search('text newline or',3))
    def test_every_extracted_token_is_quoted_in_native_match(self):
        statements=[]
        self.retriever.lexical.db.set_trace_callback(statements.append)
        self.retriever.lexical.search('text OR newline',k=3)
        self.assertTrue(any('MATCH' in statement and '\'"text" OR "or" OR "newline"\'' in statement for statement in statements))
    def test_both_branches_filter_before_candidate_limit(self):
        policy={'version':{'$eq':'3.13'}}
        result=self.retriever.search(self.query,k=1,candidate_budget=1,policy=policy)
        for branch in ['lexical','vector','results']:
            self.assertTrue(result[branch]);self.assertEqual({r['version'] for r in result[branch]},{'3.13'})
    def test_empty_eligible_corpus_returns_empty_lists(self):
        result=self.retriever.search(self.query,policy={'version':{'$eq':'9.99'}})
        self.assertEqual([result[key] for key in ('lexical','vector','results')],[[],[],[]])
    def test_exact_full_question_goes_to_saved_vector_adapter(self):
        result=self.retriever.search(self.query)
        self.assertEqual(result['query'],self.query)
        with self.assertRaisesRegex(ValueError,'unrecorded_development_query'):self.retriever.search(' '.join(question_terms(self.query)))
    def test_native_sqlite_and_langchain_orders_are_retained(self):
        result=self.retriever.search(self.query)
        self.assertEqual(result['vector'],self.retriever.vector.search(self.query,k=3))
        self.assertEqual(result['lexical'],self.retriever.lexical.search(self.query,k=3))
        self.assertEqual(len({r['chunk_id'] for r in result['results']}),len(result['results']))

if __name__=='__main__':unittest.main()
