import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from evaluation import CONFIG,load_inputs,requests_from_cases,run_rankings,compare_runs,reannotate,validate_run
from evaluation_bindings import bind_targets,metrics
from version_documents import build_snapshot,canonical_hash

class UpdatedCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before,cls.after,cls.cases,cls.annotations=load_inputs();cls.requests=requests_from_cases(cls.cases)
        cls.first=run_rankings(cls.before,cls.requests);cls.second=run_rankings(cls.after,cls.requests)
    def comparison(self,annotations=None):return compare_runs(self.before,self.after,self.first,self.second,self.cases,self.annotations if annotations is None else annotations)
    def test_baseline_exact_published_snapshot(self):
        built=build_snapshot(Path(__file__).parent/'fixtures/baseline/source-manifest.json');self.assertEqual(built,self.before)
    def test_synthetic_update_retains_original_summary_prefix(self):
        old=next(d for d in self.before['documents'] if d['source_id']=='path-write');new=next(d for d in self.after['documents'] if d['source_id']=='path-write')
        self.assertTrue(new['text'].startswith(old['text']));self.assertIn('SYNTHETIC',new['text']);self.assertNotEqual(old['sha256'],new['sha256'])
    def test_stale_targets_refused(self):
        with self.assertRaisesRegex(ValueError,'target_binding_not_bijective'):bind_targets(self.after,self.cases)
    def test_exact_reannotation_receipts(self):
        revised,receipts=reannotate(self.before,self.after,self.cases,self.annotations)
        self.assertEqual(len(receipts),2)
        for receipt in receipts:
            self.assertNotEqual(receipt['old_target']['source_text_sha256'],receipt['new_target']['source_text_sha256'])
            self.assertEqual(receipt['new_current_chunk_ids'],[receipt['new_target']['chunk_id']])
        self.assertNotEqual(revised[0]['expected'],self.cases[0]['expected'])
    def test_changed_new_hash_refused(self):
        annotations=copy.deepcopy(self.annotations);annotations[0]['new_target']['source_text_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'invalid_reannotation'):reannotate(self.before,self.after,self.cases,annotations)
    def test_changed_new_chunk_id_refused(self):
        annotations=copy.deepcopy(self.annotations);annotations[0]['new_target']['chunk_id']='0'*64
        with self.assertRaisesRegex(ValueError,'invalid_reannotation'):reannotate(self.before,self.after,self.cases,annotations)
    def test_changed_old_hash_refused(self):
        annotations=copy.deepcopy(self.annotations);annotations[0]['old_target']['source_text_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'invalid_reannotation'):reannotate(self.before,self.after,self.cases,annotations)
    def test_receipt_snapshot_and_duplicate_refused(self):
        changed=copy.deepcopy(self.annotations);changed[0]['new_snapshot_id']=self.before['snapshot_id']
        for annotations in [changed,self.annotations+self.annotations[:1]]:
            with self.assertRaisesRegex(ValueError,'invalid_reannotation'):reannotate(self.before,self.after,self.cases,annotations)
    def test_deleted_target_not_silently_reassigned(self):
        result=self.comparison();self.assertEqual(result['not_comparable_cases'],['json-result-type'])
        row=next(r for r in result['per_case'] if r['case_id']=='json-result-type');self.assertEqual(row['after']['reason'],'deleted_target_source');self.assertIsNone(row['after']['metrics'])
        deleted=copy.deepcopy(self.annotations[0]);deleted['case_id']='json-result-type';deleted['old_target']=self.cases[2]['expected']['targets'][0]
        with self.assertRaises(ValueError):reannotate(self.before,self.after,self.cases,[deleted])
    def test_no_reannotation_retains_stale_cases(self):
        result=self.comparison([]);self.assertEqual(len(result['not_comparable_cases']),3);self.assertEqual(result['paired_aggregate']['1']['paired_supported_denominator'],0)
    def test_unsupported_metrics_null_and_denominator_excluded(self):
        result=self.comparison();row=next(r for r in result['per_case'] if r['case_id']=='backup-schedule')
        self.assertEqual(row['comparison'],'unsupported-excluded')
        for side in ['before','after']:
            for metric in row[side]['metrics'].values():self.assertIsNone(metric['recall_at_k']);self.assertIsNone(metric['reciprocal_rank_at_k']);self.assertIsNone(metric['miss'])
        self.assertEqual(result['paired_aggregate']['1']['paired_supported_denominator'],2)
    def test_rank_and_miss_arithmetic(self):
        result=metrics([{'chunk_id':'x'},{'chunk_id':'target'}],['target'],1)
        self.assertEqual(result['target_ranks'],[2]);self.assertEqual(result['recall_at_k'],0);self.assertEqual(result['reciprocal_rank_at_k'],0)
        self.assertEqual(metrics([{'chunk_id':'x'},{'chunk_id':'target'}],['target'],2)['reciprocal_rank_at_k'],.5)
    def test_retrieval_rejects_labels_as_inputs(self):
        requests=copy.deepcopy(self.requests);requests[0]['expected']=self.cases[0]['expected']
        with self.assertRaisesRegex(ValueError,'labels_not_retrieval_inputs'):run_rankings(self.before,requests)
    def test_labels_do_not_change_rankings(self):
        changed=copy.deepcopy(self.cases);changed[0]['expected']['targets'][0]['source_text_sha256']='0'*64
        self.assertEqual(run_rankings(self.before,requests_from_cases(changed)),self.first)
    def test_changed_request_cannot_be_compared(self):
        requests=copy.deepcopy(self.requests);requests[0]['query']='Different query'
        changed=run_rankings(self.after,requests)
        with self.assertRaisesRegex(ValueError,'comparison_context_mismatch'):compare_runs(self.before,self.after,self.first,changed,self.cases,self.annotations)
    def test_changed_configuration_refused(self):
        for config in [{**CONFIG,'candidate_budget':True},{**CONFIG,'candidate_budget':2},{**CONFIG,'cutoffs':[1,3]}]:
            with self.assertRaisesRegex(ValueError,'unsupported_config'):run_rankings(self.after,self.requests,config)
    def test_mutated_snapshot_refused(self):
        changed=copy.deepcopy(self.after);changed['documents'][0]['text']+=' altered'
        with self.assertRaisesRegex(ValueError,'invalid_snapshot'):run_rankings(changed,self.requests)
    def test_changed_ranked_payload_refused(self):
        changed=copy.deepcopy(self.second);changed['rows'][0]['ranked'][0]['text']+=' altered'
        with self.assertRaisesRegex(ValueError,'invalid_run_binding'):validate_run(self.after,changed)
    def test_rehashed_rank_order_refused(self):
        changed=copy.deepcopy(self.second);changed['rows'][0]['ranked'].reverse()
        changed['run_sha256']=canonical_hash({k:v for k,v in changed.items() if k!='run_sha256'})
        with self.assertRaisesRegex(ValueError,'invalid_run_binding'):validate_run(self.after,changed)
    def test_rehashed_native_score_refused(self):
        changed=copy.deepcopy(self.second);changed['rows'][0]['ranked'][0]['native_score']=123.0
        changed['run_sha256']=canonical_hash({k:v for k,v in changed.items() if k!='run_sha256'})
        with self.assertRaisesRegex(ValueError,'invalid_run_binding'):validate_run(self.after,changed)
    def test_rehashed_dropped_result_refused(self):
        changed=copy.deepcopy(self.second);changed['rows'][0]['ranked'].pop()
        changed['run_sha256']=canonical_hash({k:v for k,v in changed.items() if k!='run_sha256'})
        with self.assertRaisesRegex(ValueError,'invalid_run_binding'):validate_run(self.after,changed)
    def test_stale_run_refused(self):
        with self.assertRaisesRegex(ValueError,'invalid_run_binding'):validate_run(self.after,self.first)
    def test_heldout_split_refused(self):
        cases=copy.deepcopy(self.cases);cases[0]['split']='heldout'
        with self.assertRaisesRegex(ValueError,'development_only'):requests_from_cases(cases)
    def test_malformed_request_and_config_values_refused(self):
        requests=copy.deepcopy(self.requests);requests[0]['case_id']=[]
        with self.assertRaises(ValueError):run_rankings(self.before,requests)
        with self.assertRaisesRegex(ValueError,'unsupported_config'):run_rankings(self.before,self.requests,{'invalid':object()})
    def test_fixture_byte_mutation_refused(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'fixtures';shutil.copytree(Path(__file__).parent/'fixtures',target)
            (target/'updated-snapshot.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'fixture_hash_mismatch'):load_inputs(target)
if __name__=='__main__':unittest.main()
