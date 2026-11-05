import unittest
from core import load
from curate_traces import partition
from optimize_retrieval import Candidate, evaluate, select


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        self.split = partition(load('cases.json'), load('splits.json'))

    def test_empty_development_data_cannot_select(self):
        with self.assertRaisesRegex(ValueError, 'empty case set'):
            select([])

    def test_ties_prefer_less_context(self):
        cases = [c for c in self.split['development'] if c['id'].endswith('-direct')]
        small, large = Candidate('small', True, 1), Candidate('large', True, 2)
        selected, _ = select(cases, candidates=(large, small))
        self.assertEqual(selected.name, 'small')

    def test_test_labels_do_not_change_the_frozen_selection(self):
        before, _ = select(self.split['development'])
        for case in self.split['test']:
            case['expected_doc'] = 'not-a-document'
        after, _ = select(self.split['development'])
        self.assertEqual(before, after)
        self.assertEqual(evaluate(after, self.split['test'])['hits'], 0)

    def test_invalid_top_k_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'invalid search'):
            evaluate(Candidate('unbounded', True, 100), self.split['development'])


if __name__ == '__main__':
    unittest.main()
