import copy
import unittest
from unittest.mock import patch
from assembler import RequiredContextTooLarge,escape
from budget_windows import assemble_windows,make_request
from fixture_cases import normal_case,literal_case,QUESTION,LITERAL
from surround import expand_context
import tokenizer


class BudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.counter=tokenizer.counter()

    def setUp(self):self.index,self.seeds,self.windows=normal_case()

    def test_full_serialization_is_recounted_and_whole_windows_are_kept(self):
        result=assemble_windows(self.index,self.windows,self.seeds,QUESTION,self.counter,context_limit=8192)
        self.assertEqual(result['input_tokens'],self.counter.count_request(result['messages'],result['tools']))
        self.assertEqual(set(result['kept_evidence']),{g['window_id'] for g in self.windows['groups']})
        user=result['messages'][1]['content']
        for group in self.windows['groups']:self.assertIn(escape(group['text']),user)
        separate=result['separate_text_counts']
        self.assertNotEqual(sum(separate.values()),result['input_tokens'])

    def test_exact_first_window_budget_drops_other_windows_atomically(self):
        generous=assemble_windows(self.index,self.windows,self.seeds,QUESTION,self.counter,context_limit=8192)
        first=[t for t in generous['trace'] if t['section']=='evidence'][0]
        required=generous['trace'][0]['tokens']
        limit=required+first['tokens']+128+32
        tight=assemble_windows(self.index,self.windows,self.seeds,QUESTION,self.counter,context_limit=limit)
        self.assertEqual(tight['kept_evidence'],[first['id']])
        self.assertTrue(tight['dropped_evidence'])
        self.assertLessEqual(tight['input_tokens'],tight['input_budget'])
        for group in self.windows['groups']:
            present=escape(group['text']) in tight['messages'][1]['content']
            self.assertEqual(present,group['window_id'] in tight['kept_evidence'])

    def test_seed_rank_priority_is_explicit_and_missing_ranking_rejected(self):
        request,receipts=make_request(self.index,self.windows,self.seeds,QUESTION)
        for passage,receipt in zip(request.evidence,receipts):self.assertEqual(passage.score,-receipt['priority_seed_rank'])
        with self.assertRaisesRegex(ValueError,'seed_ranking_mismatch'):make_request(self.index,self.windows,[],QUESTION)

    def test_changed_group_payload_span_ids_and_missing_seed_rejected(self):
        for field,value in [('text','altered'),('start',-1),('chunk_ids',[]),('seed_ranks',[])]:
            changed=copy.deepcopy(self.windows);changed['groups'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):make_request(self.index,changed,self.seeds,QUESTION)

    def test_required_context_overflow_is_rejected(self):
        with self.assertRaises(RequiredContextTooLarge):assemble_windows(self.index,self.windows,self.seeds,QUESTION,self.counter,context_limit=256,max_new_tokens=64,margin=16,instructions='Retain the required instruction. '*200)

    def test_empty_retrieval_preserves_question_and_system(self):
        windows=expand_context(self.index,[],radius=1)
        result=assemble_windows(self.index,windows,[],QUESTION,self.counter)
        self.assertEqual(result['kept_evidence'],[])
        self.assertEqual(result['messages'][1]['content'],QUESTION)
        self.assertEqual(result['messages'][0]['role'],'system')

    def test_literal_delimiters_are_escaped_without_new_roles(self):
        index,seeds,windows=literal_case()
        result=assemble_windows(index,windows,seeds,QUESTION,self.counter,context_limit=2048)
        text=result['messages'][1]['content']
        self.assertNotIn(LITERAL,text);self.assertIn(escape(LITERAL),text)
        self.assertEqual([m['role'] for m in result['messages']],['system','user'])
        self.assertEqual(text.count('<evidence '),1)

    def test_invalid_fixture_budget_values_are_rejected(self):
        for values in [{'context_limit':True},{'max_new_tokens':True},{'margin':True},{'context_limit':128,'max_new_tokens':128}]:
            with self.subTest(values=values),self.assertRaises(ValueError):make_request(self.index,self.windows,self.seeds,QUESTION,**values)

    def test_changed_tokenizer_file_hash_is_rejected(self):
        with patch.dict(tokenizer.MANIFEST['files'],{'tokenizer.json':'0'*64}):
            with self.assertRaisesRegex(RuntimeError,'missing or changed'):tokenizer.GemmaCounter()

if __name__=='__main__':unittest.main()
