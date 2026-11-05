import unittest
from unittest.mock import patch
from core import Task
from delegation import gather


class DelegationTests(unittest.TestCase):
    def setUp(self):
        self.jobs = [Task('a', 'rollback', 'rollback staging'), Task('b', 'tokens', 'tokens staging')]

    def test_duplicate_worker_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unique'):
            gather([self.jobs[0], self.jobs[0]])

    def test_unfinished_worker_blocks_the_merge(self):
        with patch('delegation.worker', return_value={'stop': 'turn_limit'}):
            self.assertEqual(gather(self.jobs)['stop'], 'incomplete')

    def test_workers_have_independent_document_observations(self):
        r = gather(self.jobs)
        self.assertEqual(r['workers']['a']['citation'], 'rollback-v2')
        self.assertEqual(r['workers']['b']['citation'], 'tokens-v2')
        a_read = r['workers']['a']['trace'][1]['result']['id']
        b_read = r['workers']['b']['trace'][1]['result']['id']
        self.assertNotEqual(a_read, b_read)

    def test_fanout_has_an_explicit_limit(self):
        with self.assertRaises(ValueError):
            gather([Task(str(i), 'rollback', 'rollback') for i in range(3)])


if __name__ == '__main__':
    unittest.main()
