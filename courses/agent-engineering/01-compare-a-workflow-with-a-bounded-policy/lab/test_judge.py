import unittest
from core import load
from judge_trials import confusion, format_grader, trial_metrics


class JudgeTests(unittest.TestCase):
    def test_a_well_formatted_wrong_answer_is_a_false_positive(self):
        rows = [r for r in load('judge-cases.json') if r['id'] == 'invented-command']
        self.assertEqual(confusion(rows, lambda r: format_grader(r['result']))['FP'], 1)

    def test_no_trials_cannot_produce_a_score(self):
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            trial_metrics([], 1)

    def test_k_cannot_exceed_the_trial_count(self):
        with self.assertRaises(ValueError):
            trial_metrics([True], 2)

    def test_any_success_and_all_success_are_different(self):
        r = trial_metrics([True, True, False, True], 2)
        self.assertTrue(r['observed_any'])
        self.assertFalse(r['observed_all'])
        self.assertEqual(r['pass_at_k'], 1)
        self.assertAlmostEqual(r['all_k_iid_plugin'], .5625)

    def test_zero_successes_score_zero(self):
        r = trial_metrics([False, False, False], 2)
        self.assertEqual(r['pass_at_k'], 0)
        self.assertEqual(r['all_k_iid_plugin'], 0)


if __name__ == '__main__':
    unittest.main()
