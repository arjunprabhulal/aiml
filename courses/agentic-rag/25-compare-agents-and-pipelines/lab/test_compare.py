import copy
import json
from pathlib import Path
import unittest
from tools import load_snapshot
from compare import execute,bind_targets,evaluate,check_outcome,SHARED_LIMITS
from limits import Limits


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.snapshot=load_snapshot();self.cases=json.loads((Path(__file__).parent/'fixtures/development-cases.json').read_text())

    def questions(self,cases):return [{'case_id':c['id'],'question':c['input'],'version':c['tags']['python_version']} for c in cases]

    def test_same_questions_versions_corpus_and_maximum_budgets(self):
        trials=execute(self.snapshot,self.questions(self.cases))
        self.assertEqual(len(trials),8)
        for case in self.cases:
            selected=[t for t in trials if t['case_id']==case['id']]
            self.assertEqual({t['policy'] for t in selected},{'fixed_pipeline','scripted_refinement'})
            self.assertTrue(all(t['question']==case['input'] and t['version']==case['tags']['python_version'] for t in selected))
            self.assertEqual(selected[0]['runtime']['limits'],selected[1]['runtime']['limits'])

    def test_labels_are_joined_only_after_policy_execution(self):
        changed=copy.deepcopy(self.cases)
        for case in changed:case['expected']={'targets':[]};case['class']='unsupported'
        first=execute(self.snapshot,self.questions(self.cases));second=execute(self.snapshot,self.questions(changed))
        self.assertEqual(first,second)

    def test_exact_target_binding_maps_legacy_ids_and_refuses_changed_hash(self):
        labels,receipts=bind_targets(self.snapshot,self.cases)
        self.assertEqual(len(receipts),3)
        self.assertTrue(all(r['legacy_chunk_id']!=r['current_passage_id'] for r in receipts))
        changed=copy.deepcopy(self.cases);changed[0]['expected']['targets'][0]['chunk_text_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'not_bijective'):bind_targets(self.snapshot,changed)
        changed=copy.deepcopy(self.cases);changed[0]['split']='held_out'
        with self.assertRaisesRegex(ValueError,'development_only'):bind_targets(self.snapshot,changed)

    def test_failures_and_unsupported_incomplete_trials_are_retained(self):
        labels,_=bind_targets(self.snapshot,self.cases);checked,summary=evaluate(execute(self.snapshot,self.questions(self.cases)),labels)
        self.assertEqual(len(checked),8)
        self.assertTrue(any(t['outcome_check']['status']=='fail' for t in checked))
        unsupported=[t for t in checked if t['case_id']=='backup-schedule']
        self.assertEqual(len(unsupported),2)
        self.assertTrue(all(t['outcome_check']['status']=='incomplete' for t in unsupported))
        self.assertTrue(all(sum(counts.values())==4 for counts in summary.values()))

    def test_budget_limited_and_controller_failed_states_do_not_become_passes(self):
        labels,_=bind_targets(self.snapshot,self.cases)
        trial=execute(self.snapshot,self.questions(self.cases[:1]),Limits(max_steps=0))[0]
        self.assertEqual(check_outcome(trial,labels[trial['case_id']])['status'],'incomplete')
        trial['runtime']['controller_status']='failed'
        self.assertEqual(check_outcome(trial,labels[trial['case_id']])['status'],'fail')

    def test_changed_read_text_or_version_does_not_pass_target_check(self):
        labels,_=bind_targets(self.snapshot,self.cases)
        trials=execute(self.snapshot,self.questions(self.cases))
        passed=next(t for t in trials if check_outcome(t,labels[t['case_id']])['status']=='pass')
        for field,value in [('text','altered'),('version','9.9'),('source_sha256','altered')]:
            trial=copy.deepcopy(passed)
            for observation in trial['runtime']['observations']:
                if observation['tool']=='read':observation['result'][field]=value
            self.assertNotEqual(check_outcome(trial,labels[trial['case_id']])['status'],'pass')

    def test_missing_or_duplicate_trials_refuse_join(self):
        labels,_=bind_targets(self.snapshot,self.cases);trials=execute(self.snapshot,self.questions(self.cases))
        with self.assertRaisesRegex(ValueError,'join'):evaluate(trials[:-1],labels)
        with self.assertRaisesRegex(ValueError,'join'):evaluate([*trials,trials[0]],labels)

if __name__=='__main__':unittest.main()
