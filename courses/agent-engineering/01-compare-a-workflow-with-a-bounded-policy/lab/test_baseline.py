import unittest
from core import Documents, Task, load, outcome, task_from
from task_baseline import compare, keyword_route, workflow


class BaselineTests(unittest.TestCase):
    def test_production_is_outside_the_task(self):
        with self.assertRaisesRegex(ValueError, 'only covers staging'):
            Task('a', 'deploy', 'deploy', environment='production')

    def test_unknown_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unsupported documentation version'):
            Task('a', 'deploy', 'deploy', version='v9')

    def test_ambiguous_workflow_route_stops(self):
        r = keyword_route(Task('a', 'mixed', 'deploy and rollback staging'))
        self.assertEqual(r['stop'], 'needs_review')
        self.assertEqual(r['tool_calls'], 0)

    def test_wrong_version_page_cannot_be_read(self):
        with self.assertRaises(ValueError):
            Documents().read('deploy-v1', 'v2')

    def test_completion_message_does_not_pass(self):
        case = load('cases.json')[0]
        self.assertFalse(outcome(case, {'stop': 'final', 'answer': 'Done', 'citation': case['expected_doc']}))

    def test_both_strategies_cover_the_same_cases(self):
        rows = compare(load('cases.json'))
        self.assertEqual({r['total'] for r in rows.values()}, {18})
        self.assertTrue(all(r['tool_calls'] >= r['passed'] for r in rows.values()))

    def test_workflow_and_loop_share_retrieval_and_tool_budget(self):
        rows = compare(load('cases.json'))
        self.assertEqual(rows['search/read workflow'], rows['scripted loop'])


if __name__ == '__main__':
    unittest.main()
