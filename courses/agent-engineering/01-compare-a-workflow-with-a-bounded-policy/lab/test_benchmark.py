import unittest
from benchmark import benchmark


class BenchmarkTests(unittest.TestCase):
    def test_done_message_does_not_override_failing_environment(self):
        result = benchmark([{'id': 'bad', 'expression': 'attempt <= max_attempts', 'reported_done': True}])[0]
        self.assertTrue(result['reported_done'])
        self.assertEqual(result['grade']['outcome'], 'failed')

    def test_duplicate_trial_ids_are_rejected(self):
        c = {'id': 'a', 'expression': 'attempt < max_attempts', 'reported_done': True}
        with self.assertRaisesRegex(ValueError, 'unique'):
            benchmark([c, c])

    def test_valid_behavior_passes_even_without_a_done_claim(self):
        c = {'id': 'quiet', 'expression': 'attempt < max_attempts', 'reported_done': False}
        self.assertEqual(benchmark([c])[0]['grade']['outcome'], 'passed')

    def test_no_trials_cannot_be_reported_as_success(self):
        with self.assertRaises(ValueError):
            benchmark([])


if __name__ == '__main__':
    unittest.main()
