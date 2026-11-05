import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from evaluator import DEFAULT_CONFIG,execute_trials,evaluate_run,release_gate,check_integrity
from tools import load_snapshot
from version_documents import canonical_hash
class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot=load_snapshot();cls.cases=json.loads((Path(__file__).parent/'fixtures/development-cases.json').read_text());cls.config=copy.deepcopy(DEFAULT_CONFIG)
        cls.questions=[{'case_id':c['id'],'question':c['input'],'version':c['tags']['python_version']} for c in cls.cases]
        cls.trials=execute_trials(cls.snapshot,cls.questions,cls.config);cls.report=evaluate_run(cls.snapshot,cls.cases,cls.trials,cls.config)
    def test_labels_not_exposed_to_execution(self):
        with patch('evaluator.bind_targets',side_effect=AssertionError('labels read before execution')):
            self.assertEqual(len(execute_trials(self.snapshot,self.questions,self.config)),16)
        bad=copy.deepcopy(self.questions);bad[0]['expected']={}
        with self.assertRaisesRegex(ValueError,'projection'):execute_trials(self.snapshot,bad,self.config)
    def test_exact_read_provenance_not_only_known_id_or_self_hash(self):
        t=copy.deepcopy(next(t for t in self.trials if t['policy']=='scripted_refinement'))
        obs=next(o for o in t['runtime']['observations'] if o['tool']=='read');row=obs['result'];row['text']='x'*len(row['text']);row['result_sha256']=canonical_hash({k:v for k,v in row.items() if k!='result_sha256'})
        event=next(e for e in t['runtime']['trace'] if e.get('action',{}).get('tool')=='read');event['result']=copy.deepcopy(row)
        self.assertEqual(check_integrity(self.snapshot,t,self.config['limits'])['status'],'fail')
    def test_budget_totals_and_admission_trace_are_independent(self):
        t=copy.deepcopy(self.trials[0]);t['runtime']['usage']['steps']=0
        self.assertEqual(check_integrity(self.snapshot,t,self.config['limits'])['status'],'fail')
        t=copy.deepcopy(self.trials[0]);t['runtime']['trace'][0]['invoked']=False
        self.assertEqual(check_integrity(self.snapshot,t,self.config['limits'])['status'],'fail')
    def test_read_requires_preceding_issued_search(self):
        t=copy.deepcopy(self.trials[0]);t['runtime']['trace']=t['runtime']['trace'][1:]
        self.assertEqual(check_integrity(self.snapshot,t,self.config['limits'])['status'],'fail')
    def test_eligible_version_checked_before_target_outcome(self):
        t=copy.deepcopy(self.trials[0]);t['version']='3.13'
        self.assertEqual(check_integrity(self.snapshot,t,self.config['limits'])['status'],'fail')
    def test_unsupported_is_incomplete_not_supported_pass(self):
        rows=[t for t in self.report['trials'] if t['case_id']=='backup-schedule']
        self.assertTrue(all(t['task_outcome']['status']=='incomplete' for t in rows))
        gate=release_gate(self.report,self.report['identity'],'scripted_refinement');self.assertEqual(gate['supported_trials'],6);self.assertEqual(gate['unsupported_trials'],2)
    def test_full_frozen_cases_retain_failures_and_gate_fail(self):
        self.assertTrue(all(t['execution_integrity']['status']=='pass' for t in self.report['trials']))
        self.assertEqual(release_gate(self.report,self.report['identity'],'fixed_pipeline')['status'],'FAIL')
        self.assertEqual(release_gate(self.report,self.report['identity'],'scripted_refinement')['status'],'FAIL')
    def test_actual_subset_can_meet_explicit_gate_policy(self):
        # This branch test is a declared subset, not the released full-suite result.
        cases=[c for c in self.cases if c['id']=='replace-file'];trials=[t for t in self.trials if t['case_id']=='replace-file']
        report=evaluate_run(self.snapshot,cases,trials,self.config)
        self.assertEqual(release_gate(report,report['identity'],'scripted_refinement')['status'],'PASS')
    def test_missing_target_and_join_refused(self):
        cases=copy.deepcopy(self.cases);cases[0]['expected']['targets'][0]['chunk_text_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'target_binding'):evaluate_run(self.snapshot,cases,self.trials,self.config)
        with self.assertRaisesRegex(ValueError,'trial_join'):evaluate_run(self.snapshot,self.cases,self.trials[:-1],self.config)
    def test_identity_changed_config_and_repeat_disagreement_not_comparable(self):
        self.assertEqual(release_gate(self.report,{**self.report['identity'],'corpus_id':'other'},'scripted_refinement')['status'],'NOTCOMPARABLE')
        report=copy.deepcopy(self.report);report['configuration']['limits']['max_steps']=5
        self.assertEqual(release_gate(report,self.report['identity'],'scripted_refinement')['status'],'NOTCOMPARABLE')
        report=copy.deepcopy(self.report);report['trials'][1]['runtime']['terminal_reason']='different'
        self.assertEqual(release_gate(report,report['identity'],'scripted_refinement')['status'],'NOTCOMPARABLE')
    def test_question_and_trial_binding_and_config_types(self):
        trials=copy.deepcopy(self.trials);trials[0]['question']='other'
        with self.assertRaisesRegex(ValueError,'question_binding'):evaluate_run(self.snapshot,self.cases,trials,self.config)
        trials=copy.deepcopy(self.trials);trials[0]['trial_id']='other'
        with self.assertRaisesRegex(ValueError,'trial_id'):evaluate_run(self.snapshot,self.cases,trials,self.config)
        config=copy.deepcopy(self.config);config['repeats']=True
        with self.assertRaisesRegex(ValueError,'repeats'):execute_trials(self.snapshot,self.questions,config)
    def test_real_failure_and_corruption_and_budget_scenarios(self):
        from run import run
        r=run()
        self.assertEqual(r['actual_tool_failure']['gate']['status'],'FAIL');self.assertEqual(r['corruption_fixture']['gate']['status'],'FAIL');self.assertEqual(r['step_budget']['gate']['status'],'FAIL')
        failed=[t for t in r['actual_tool_failure']['report']['trials'] if t['runtime']['controller_status']=='failed'];self.assertEqual(len(failed),2);self.assertTrue(all(t['task_outcome']['status']=='fail' for t in failed))
        limited=[t for t in r['step_budget']['report']['trials'] if t['case_id']!='backup-schedule'];self.assertTrue(all(t['task_outcome']['status']=='incomplete' for t in limited))
if __name__=='__main__':unittest.main()
