import copy
import unittest
from vector_retriever import load_inputs
from compare import bind_targets,evaluate,metrics,retrieve_runs,CONFIGURATIONS


class CompareTests(unittest.TestCase):
    def setUp(self):self.snapshot,self.embeddings,self.cases=load_inputs()

    def questions(self,cases):return [{'case_id':c['id'],'query':c['input'],'version':c['tags']['python_version']} for c in cases]

    def test_legacy_labels_bind_to_exact_current_chunk(self):
        bindings,receipts=bind_targets(self.snapshot,self.cases)
        self.assertEqual(len(receipts),3)
        for receipt in receipts:self.assertNotEqual(receipt['legacy_chunk_id'],receipt['current_chunk_id'])
        self.assertEqual(bindings['backup-schedule']['target_chunk_ids'],[])

    def test_changed_target_hash_missing_and_duplicate_bindings_fail(self):
        for change in ['hash','source','duplicate','heldout']:
            cases=copy.deepcopy(self.cases)
            if change=='hash':cases[0]['expected']['targets'][0]['chunk_text_sha256']='x'
            elif change=='source':cases[0]['expected']['targets'][0]['source_id']='missing'
            elif change=='duplicate':cases[0]['expected']['targets']*=2
            else:cases[0]['split']='held_out'
            with self.subTest(change=change),self.assertRaises(ValueError):bind_targets(self.snapshot,cases)

    def test_labels_join_after_retrieval_and_cannot_change_rankings(self):
        changed=copy.deepcopy(self.cases)
        for case in changed:case['expected']={'targets':[],'status':'unsupported'}
        first=retrieve_runs(self.snapshot,self.embeddings,self.questions(self.cases))
        second=retrieve_runs(self.snapshot,self.embeddings,self.questions(changed))
        self.assertEqual(first,second)
        self.assertTrue(all(set(run['rankings'])==set(CONFIGURATIONS) for run in first))

    def test_metrics_rank_recall_and_reciprocal_rank(self):
        rows=[{'chunk_id':'a'},{'chunk_id':'b'},{'chunk_id':'c'}]
        self.assertEqual(metrics(rows,['b','c'],1)['recall_at_k'],0)
        result=metrics(rows,['b','c'],2)
        self.assertEqual(result['target_ranks'],[2,3]);self.assertEqual(result['recall_at_k'],0.5);self.assertEqual(result['reciprocal_rank_at_k'],0.5)
        with self.assertRaisesRegex(ValueError,'duplicate'):metrics([{'chunk_id':'a'},{'chunk_id':'a'}],['a'],1)

    def test_unsupported_excluded_from_aggregate_and_reported_separately(self):
        runs=retrieve_runs(self.snapshot,self.embeddings,self.questions(self.cases))
        labels,_=bind_targets(self.snapshot,self.cases);result=evaluate(runs,labels)
        self.assertEqual(result['supported_case_count'],3);self.assertEqual(result['unsupported_case_count'],1)
        for name in CONFIGURATIONS:
            self.assertEqual(result['aggregate'][name]['1']['supported_case_count'],3)
        unsupported=next(r for r in result['per_query'] if r['case_id']=='backup-schedule')
        self.assertTrue(all(unsupported['configurations'][name]['1']['recall_at_k'] is None for name in CONFIGURATIONS))
        self.assertEqual(result['unsupported_candidate_behavior'][0]['case_id'],'backup-schedule')

    def test_case_join_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'join'):evaluate([],{'extra':{}})

if __name__=='__main__':unittest.main()
