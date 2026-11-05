import unittest
from unittest.mock import patch
import urllib.error
from core import Task, load, outcome, run, scripted, task_from
from provider import OllamaPolicy


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.task = Task('rollback', 'rollback', 'rollback staging')

    def test_unknown_tool_is_rejected_before_dispatch(self):
        r = run(self.task, lambda *_: {'action': 'shell', 'query': 'deploy'})
        self.assertEqual((r['stop'], r['tool_calls']), ('invalid_decision', 0))

    def test_repeated_search_stops_at_tool_limit(self):
        r = run(self.task, lambda *_: {'action': 'search', 'query': 'rollback'}, max_tools=1)
        self.assertEqual((r['stop'], r['tool_calls']), ('tool_limit', 1))

    def test_turn_limit_is_distinct_from_final(self):
        r = run(self.task, scripted, max_turns=1)
        self.assertEqual((r['stop'], r['turns']), ('turn_limit', 1))

    def test_unread_citation_cannot_finish(self):
        r = run(self.task, lambda *_: {'action': 'final', 'answer': 'docuctl rollback', 'citation': 'rollback-v2'})
        self.assertEqual(r['stop'], 'unread_citation')

    def test_invented_command_fails_the_independent_outcome(self):
        case = next(c for c in load('cases.json') if c['id'] == 'rollback-direct')
        r = run(task_from(case), scripted)
        self.assertTrue(outcome(case, r))
        self.assertFalse(outcome(case, {**r, 'answer': 'docuctl undo staging'}))

    def test_transport_failure_is_not_a_final_answer(self):
        def unavailable(*_):
            raise urllib.error.URLError('unavailable fixture server')
        self.assertEqual(run(self.task, unavailable)['stop'], 'provider_error')

    def test_provider_limit_makes_no_fifth_request(self):
        policy = OllamaPolicy('fixture-model')
        policy.requests = 4
        with patch('provider.urllib.request.build_opener') as opener:
            with self.assertRaisesRegex(ValueError, 'request limit'):
                policy(self.task, [])
            opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
