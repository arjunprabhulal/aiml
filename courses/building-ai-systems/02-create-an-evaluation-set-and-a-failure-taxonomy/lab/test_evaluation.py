import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from evaluate_cases import record, stable_result, harness
from systems import ContractSystem, PAGES
import task

ROOT = Path(__file__).resolve().parent


class ApplicationEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = record()
        cls.cases = harness.load_cases(ROOT / 'cases.json', harness.load_task('task'))

    def failures(self, fault):
        return self.result['reports'][fault]['first_failures']

    def test_correct_function_passes_required_refusals_too(self):
        report = self.result['reports']['none']
        self.assertEqual(report['summary']['development']['pass'], 12)
        self.assertFalse(self.failures('none'))
        self.assertTrue(any(row['reason'].startswith('rejected as expected:') for row in report['results']))

    def test_wrong_source_is_detected_after_a_valid_output_shape(self):
        self.assertEqual(self.failures('source')[0]['boundary'], 'source-selection')
        self.assertEqual(self.failures('source')[0]['case_id'], 'v3-production-lookup')

    def test_permission_bypass_cannot_pass_by_returning_a_valid_proposal(self):
        self.assertEqual(self.failures('permission')[0]['boundary'], 'authorization')

    def test_missing_approval_is_distinct_from_output_shape(self):
        self.assertEqual(self.failures('approval')[0]['boundary'], 'action-policy')

    def test_missing_field_stops_before_later_checkers_index_it(self):
        self.assertEqual(self.failures('format')[0]['boundary'], 'response-contract')
        self.assertEqual(self.failures('format')[0]['verdict'], 'fail')

    def test_no_output_stays_incomplete(self):
        report = self.result['reports']['no_output']
        self.assertEqual(report['summary']['development']['incomplete'], 1)
        self.assertEqual(report['summary']['development']['fail'], 0)
        self.assertEqual(self.failures('no_output')[0]['boundary'], 'dependency-or-no-output')

    def test_slice_counts_retain_failures_in_the_affected_environment(self):
        slices = self.result['reports']['source']['slices']['environment']
        self.assertEqual(slices['production']['fail'], 1)
        self.assertEqual(slices['staging']['fail'], 0)
        self.assertEqual(sum(sum(counts.values()) for counts in slices.values()), 12)

    def test_duplicate_cases_are_refused_by_the_reused_loader(self):
        data = json.loads((ROOT / 'cases.json').read_text())
        data['cases'].append(copy.deepcopy(data['cases'][0]))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cases.json'; path.write_text(json.dumps(data))
            with self.assertRaises(harness.CaseError):
                harness.load_cases(path, task)

    def test_misspelled_request_fixture_is_refused_before_execution(self):
        cases = copy.deepcopy(self.cases)
        cases['cases'][0]['input']['request']['enviroment'] = 'staging'
        with self.assertRaisesRegex(ValueError, 'unknown fields'):
            task.validate_inputs(cases)

    def test_incomplete_expectation_is_not_silently_relaxed(self):
        expected = dict(self.cases['cases'][0]['expected'])
        del expected['citation']
        with self.assertRaises(ValueError):
            task.validate_expected(expected)

    def test_case_edit_changes_the_dataset_identity(self):
        data = json.loads((ROOT / 'cases.json').read_text())
        data['cases'][0]['why'] += ' Revised acceptance rationale.'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cases.json'; path.write_text(json.dumps(data))
            changed = harness.load_cases(path, task)
        self.assertNotEqual(changed['sha256'], self.cases['sha256'])

    def test_expectation_is_independent_of_the_current_source_command(self):
        pages = copy.deepcopy(PAGES)
        pages[0]['command'] = 'incorrect replacement command'
        with patch('systems.PAGES', pages):
            report = harness.run(ContractSystem(), self.cases, task)
        row = next(r for r in report['results'] if r['case_id'] == 'v2-staging-lookup')
        self.assertEqual(row['check'], 'task-result')
        self.assertEqual(row['verdict'], 'fail')

    def test_environment_slice_cannot_disappear_with_machine_metadata(self):
        changed = copy.deepcopy(self.result)
        changed['reports']['source']['slices']['environment']['production']['fail'] = 0
        self.assertNotEqual(stable_result(self.result), stable_result(changed))

    def test_only_execution_description_locations_are_ignored(self):
        changed = copy.deepcopy(self.result)
        changed['reports']['source']['manifest']['environment'] = {'python': 'different runtime'}
        changed['reports']['source']['manifest']['started_at'] = 'later run'
        changed['reports']['source']['results'][0]['latency_s'] = 999
        self.assertEqual(stable_result(self.result), stable_result(changed))

    def test_record_matches_outcomes_and_bindings_not_incidental_timing(self):
        saved = json.loads((ROOT / 'result.json').read_text())
        self.assertEqual(stable_result(self.result), stable_result(saved))


if __name__ == '__main__':
    unittest.main()
