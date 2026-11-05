import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import analyze_slices as a


class Slices(unittest.TestCase):
    def setUp(self):
        self.cases=a.harness.load_cases(a.HERE/'cases.json',a.task)
        self.saved=json.loads((a.HERE/'saved-report.json').read_text())
        self.policy=json.loads((a.HERE/'cost-policy.json').read_text())

    def analyze(self,name='permission',report=None,policy=None):
        return a.analyze(self.cases,report or self.saved['reports'][name],policy or self.policy)

    def test_equal_pass_counts_retain_asymmetric_penalties(self):
        source=self.analyze('source')['overall'];permission=self.analyze()['overall']
        self.assertEqual(source['pass'],11);self.assertEqual(permission['pass'],11)
        self.assertEqual(source['cases'],12);self.assertEqual(source['total_cost'],8)
        self.assertEqual(permission['total_cost'],100)

    def test_critical_cross_slice_exposes_failure_in_one_of_one(self):
        result=self.analyze();critical=result['slices']['reader-production-proposal']
        self.assertEqual(critical['case_ids'],['reader-proposal'])
        self.assertEqual((critical['pass'],critical['fail'],critical['cases']),(0,1,1))
        self.assertEqual(critical['total_cost'],100)

    def test_incomplete_result_is_not_zero_cost_or_removed_from_denominator(self):
        result=self.analyze('no_output')['overall']
        self.assertEqual((result['cases'],result['pass'],result['incomplete']),(12,11,1))
        self.assertEqual(result['pass_fraction'],11/12)
        self.assertEqual(result['completion_fraction'],11/12)
        self.assertIsNone(result['total_cost']);self.assertIsNone(result['cost_per_case'])
        self.assertEqual(result['cost_interval'],[0,100])

    def test_empty_slice_has_no_rate_or_cost(self):
        result=self.analyze()['slices']['version-4-empty']
        self.assertEqual(result['cases'],0)
        for key in ('pass_fraction','completion_fraction','known_cost','total_cost','cost_interval'):
            self.assertIsNone(result[key],key)

    def test_overlapping_slices_keep_membership_and_do_not_imply_partition(self):
        result=self.analyze();id='reader-proposal'
        for name in ('all','production','version-3','reader-production-proposal'):
            self.assertIn(id,result['slices'][name]['case_ids'])
        self.assertGreater(sum(s['cases'] for s in result['slices'].values()),result['overall']['cases'])

    def test_role_default_and_literal_environment_match_existing_contract(self):
        rows=self.analyze()['ledger'];by_id={r['id']:r for r in rows}
        self.assertEqual(by_id['v3-production-lookup']['request']['role'],'reader')
        self.assertEqual(by_id['unknown-environment']['request']['environment'],'prod')
        self.assertNotIn('unknown-environment',self.analyze()['slices']['production']['case_ids'])

    def test_shuffled_results_are_joined_by_id(self):
        report=copy.deepcopy(self.saved['reports']['permission']);report['results'].reverse()
        self.assertEqual(self.analyze(report=report),self.analyze())

    def test_missing_duplicate_unknown_or_repeated_trial_refused(self):
        base=self.saved['reports']['permission']
        for change in (lambda r:r['results'].pop(),lambda r:r['results'].append(copy.deepcopy(r['results'][0])),
                       lambda r:r['results'][0].update(case_id='invented'),lambda r:r['results'][0].update(trial=1)):
            report=copy.deepcopy(base);change(report)
            with self.subTest(change=change),self.assertRaises(ValueError):self.analyze(report=report)

    def test_different_case_set_identity_refused(self):
        report=copy.deepcopy(self.saved['reports']['permission']);report['manifest']['case_set']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'case-set identities'):self.analyze(report=report)

    def test_result_metadata_and_unknown_verdict_refused(self):
        for field,value in (('split','heldout'),('class','different'),('verdict','unknown')):
            report=copy.deepcopy(self.saved['reports']['permission']);report['results'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.analyze(report=report)

    def test_missing_or_inconsistent_failure_tag_refused(self):
        for change in (lambda r:r['first_failures'].clear(),lambda r:r['first_failures'][0].update(verdict='incomplete'),
                       lambda r:r['first_failures'][0].update(reason='different')):
            report=copy.deepcopy(self.saved['reports']['permission']);change(report)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'failure tag'):self.analyze(report=report)

    def test_unknown_cost_boundary_and_unknown_incomplete_boundary_refused(self):
        for name in ('permission','no_output'):
            report=copy.deepcopy(self.saved['reports'][name]);report['first_failures'][0]['boundary']='new-boundary'
            with self.subTest(name=name),self.assertRaises(ValueError):self.analyze(name,report=report)

    def test_boolean_negative_nonfinite_and_missing_costs_refused(self):
        for value in (True,-1,float('nan'),float('inf')):
            policy=copy.deepcopy(self.policy);policy['cost_by_boundary']['authorization']=value
            with self.subTest(value=value),self.assertRaises(ValueError):self.analyze(policy=policy)
        policy=copy.deepcopy(self.policy);policy['cost_by_boundary'].pop('authorization')
        with self.assertRaises(ValueError):self.analyze(policy=policy)

    def test_incomplete_bounds_must_cover_declared_penalties(self):
        for bounds in ([0,99],[-1,100],[0,True],[0,float('inf')]):
            policy=copy.deepcopy(self.policy);policy['incomplete_interval']=bounds
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):self.analyze(policy=policy)

    def test_duplicate_or_unknown_slice_fields_refused(self):
        policy=copy.deepcopy(self.policy);policy['slices'].append(copy.deepcopy(policy['slices'][0]))
        with self.assertRaises(ValueError):self.analyze(policy=policy)
        policy=copy.deepcopy(self.policy);policy['slices'][0]['where']={'model':'invented'}
        with self.assertRaises(ValueError):self.analyze(policy=policy)

    def test_known_cost_and_unknown_bounds_are_both_retained(self):
        rows=[{'verdict':'fail','cost':8},{'verdict':'incomplete','cost':None},{'verdict':'pass','cost':0}]
        result=a.summarize(rows,self.policy)
        self.assertEqual(result['known_cost'],8);self.assertEqual(result['cost_interval'],[8,108])
        self.assertIsNone(result['total_cost'])

    def test_changed_reviewed_record_refused_before_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in (*a.INPUTS,'input-manifest.json','cost-policy.json','analyze_slices.py'):
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.HERE/name,target)
            p=root/'saved-report.json';p.write_bytes(p.read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError,'reviewed input bytes differ'):a.record(root)

    def test_revised_policy_changes_cost_not_execution_outcomes(self):
        policy=copy.deepcopy(self.policy);policy['cost_by_boundary']['source-selection']=16
        original=self.analyze('source');changed=self.analyze('source',policy=policy)
        self.assertEqual(changed['overall']['total_cost'],16)
        for key in ('cases','pass','fail','incomplete'):self.assertEqual(original['overall'][key],changed['overall'][key])

    def test_result_matches_current_saved_inputs_and_policy(self):
        self.assertEqual(a.record(),json.loads((a.HERE/'result.json').read_text()))


if __name__=='__main__':unittest.main()
