import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from agent import run, Limits, validate_decision
from evaluate import grade
from provider import ReplayModel, Gemini, Allowance, payload, decode, CONFIG
from retrieval import RetrievalTools
from tools import load_snapshot


def decision(action, **values):
    return {**dict(action=action, assessment='Controlled contract-test decision', query='',
                   source_id='', answer='', citations=[]), **values}


class Stub:
    def __init__(self, *rows):
        self.rows, self.calls = iter(rows), 0
    def decide(self, *args, **kwargs):
        self.calls += 1
        return copy.deepcopy(next(self.rows))


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tools = RetrievalTools(load_snapshot())
        self.addCleanup(self.tools.close)
    def test_model_observation_drives_refinement_and_cited_answer(self):
        quote = next(r['text'] for r in self.tools.rows.values() if r['source_id'] == 'path-write')
        model = Stub(decision('search', query='read'), decision('read', source_id='path-read'),
                     decision('search', query='overwritten'), decision('read', source_id='path-write'),
                     decision('answer', answer='Existing files are overwritten.',
                              citations=[{'source_id': 'path-write', 'quote': quote}]))
        result = run(self.tools, model, 'What happens to existing text?')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual([o['arguments']['query'] for o in result['observations'] if o['tool'] == 'search'], ['read', 'overwritten'])
    def test_unknown_action_never_invokes_a_tool(self):
        with patch.object(self.tools, 'search', side_effect=AssertionError('must not invoke')):
            result = run(self.tools, Stub(decision('shell')), 'question')
        self.assertEqual(result['reason'], 'unknown_action')
    def test_unissued_source_never_reads(self):
        with patch.object(self.tools, 'read', side_effect=AssertionError('must not invoke')):
            result = run(self.tools, Stub(decision('read', source_id='path-write')), 'question')
        self.assertEqual(result['reason'], 'unissued_source')
    def test_changed_read_rejected_before_observation(self):
        original = self.tools.read
        with patch.object(self.tools, 'read', side_effect=lambda h: {**original(h), 'text': 'invented'}):
            result = run(self.tools, Stub(decision('search', query='overwritten'), decision('read', source_id='path-write')), 'question')
        self.assertEqual(result['reason'], 'invalid_read_result')
        self.assertEqual(result['usage']['reads'], 1)
        self.assertEqual(len(result['observations']), 1)
    def test_unread_or_changed_citation_rejected(self):
        for citation in [{'source_id': 'path-write', 'quote': 'overwritten'}, {'source_id': 'path-read', 'quote': 'invented'}]:
            model = Stub(decision('search', query='read'), decision('read', source_id='path-read'),
                         decision('answer', answer='Wrong.', citations=[citation]))
            result = run(self.tools, model, 'question')
            self.assertEqual(result['reason'], 'unread_or_changed_citation')
            self.assertEqual(result['answer'], '')
    def test_search_limit_denies_before_invocation(self):
        model = Stub(decision('search', query='read'), decision('search', query='overwritten'))
        with patch.object(self.tools, 'search', wraps=self.tools.search) as search:
            result = run(self.tools, model, 'question', limits=Limits(searches=1))
        self.assertEqual(search.call_count, 1)
        self.assertEqual(result['reason'], 'search_limit')
    def test_byte_limit_denies_before_read(self):
        with patch.object(self.tools, 'read', side_effect=AssertionError('must not invoke')):
            result = run(self.tools, Stub(decision('search', query='read'), decision('read', source_id='path-read')),
                         'question', limits=Limits(source_bytes=1))
        self.assertEqual(result['reason'], 'read_or_byte_limit')
        self.assertEqual(result['usage']['reads'], 0)
    def test_duplicate_query_and_read_refused(self):
        for rows, reason in [([decision('search', query='read text'), decision('search', query='TEXT read')], 'duplicate_query'),
                             ([decision('search', query='read'), decision('read', source_id='path-read'), decision('read', source_id='path-read')], 'duplicate_read')]:
            self.assertEqual(run(self.tools, Stub(*rows), 'question')['reason'], reason)
    def test_tool_failure_consumes_admitted_attempt(self):
        with patch.object(self.tools, 'search', side_effect=RuntimeError('tool_failed')):
            result = run(self.tools, Stub(decision('search', query='text')), 'question')
        self.assertEqual(result['usage']['searches'], 1)
        self.assertEqual(result['status'], 'failed')
    def test_model_call_limit_and_deadline_are_incomplete(self):
        result = run(self.tools, Stub(decision('search', query='text')), 'question', limits=Limits(model_calls=1))
        self.assertEqual(result['reason'], 'model_call_limit')
        clock = iter([0, 181]); model = Stub()
        result = run(self.tools, model, 'question', clock=lambda: next(clock))
        self.assertEqual(result['reason'], 'deadline')
        self.assertEqual(model.calls, 0)
    def test_explicit_stop_is_distinct_from_exhaustion(self):
        result = run(self.tools, Stub(decision('stop')), 'question')
        self.assertTrue(grade({'sources': []}, result)['answer_fixture_check'])
        result['reason'] = 'model_call_limit'
        self.assertFalse(grade({'sources': []}, result)['answer_fixture_check'])
    def test_fixed_baseline_uses_original_question_and_forbids_refinement(self):
        result = run(self.tools, Stub(decision('search', query='other')), 'write text', mode='fixed')
        self.assertEqual(result['observations'][0]['arguments']['query'], 'write text')
        self.assertEqual(result['reason'], 'fixed_policy_tool_request')
    def test_version_filter_precedes_limit_and_query_syntax_is_literal(self):
        found = self.tools.search('text OR newline', version='3.13', k=1)
        self.assertEqual(len(found['results']), 1)
        self.assertEqual(found['results'][0]['version'], '3.13')
        self.assertNotIn('text', found['results'][0])
    def test_invalid_limits_and_decisions(self):
        for limits in [dict(model_calls=True), dict(searches=0), dict(seconds=301)]:
            with self.assertRaisesRegex(ValueError, 'invalid_limits'): Limits(**limits)
        for bad in [decision('answer'), decision('search', query=''), decision('stop', answer='invented'),
                    decision('stop', extra=1), decision('stop', assessment='')]:
            with self.assertRaises(ValueError): validate_decision(bad)
    def test_exact_request_replay_refuses_changed_context(self):
        messages = [{'role':'system','content':'s'}, {'role':'user','content':'u'}]
        response = {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(decision('stop'))}]}}]}
        model = ReplayModel([{'request':payload(messages, {}), 'response':response}])
        changed = copy.deepcopy(messages); changed[1]['content'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, 'replay_request_mismatch'): model.decide(changed, {})
        self.assertEqual(model.decide(messages, {})['action'], 'stop')
        with self.assertRaisesRegex(RuntimeError, 'replay_exhausted'): model.decide(messages, {})
    def test_provider_cap_is_before_network_and_config_is_explicit(self):
        allowance = Allowance(1); allowance.used = 1
        with patch('urllib.request.Request', side_effect=AssertionError('no network')):
            with self.assertRaisesRegex(RuntimeError, 'batch_request_limit'):
                Gemini(allowance).decide([{'content':'s'}, {'content':'u'}], {})
        self.assertEqual(CONFIG['thinkingConfig'], {'thinkingLevel':'LOW'})
        self.assertEqual(CONFIG['maxOutputTokens'], 1024)
        with self.assertRaisesRegex(RuntimeError, 'unfinished_model_reply'):
            decode({'candidates':[{'finishReason':'MAX_TOKENS'}]})
    def test_fixture_labels_never_enter_recorded_model_requests(self):
        for path in (Path(__file__).parent/'runs/gemini').glob('*-agent-*.json'):
            for row in json.loads(path.read_text()):
                state = json.loads(row['request']['contents'][0]['parts'][0]['text'])
                self.assertEqual(set(state), {'question','version','observations','usage','limits','schema'})
                self.assertNotIn('answer_patterns', json.dumps(state))
    def test_selected_case_replays_only_its_matched_trials(self):
        from run import execute
        with patch('urllib.request.build_opener', side_effect=AssertionError('offline only')):
            report = execute(only='serialize-and-save')
        self.assertEqual(len(report['trials']), 4)
        self.assertEqual({t['case_id'] for t in report['trials']}, {'serialize-and-save'})
    def test_all_saved_trials_replay_without_network(self):
        from run import execute
        with patch('urllib.request.build_opener', side_effect=AssertionError('offline only')):
            report = execute()
        self.assertTrue(report['trials'])
        for trial in report['trials']: self.assertTrue(trial['checks']['trajectory']['within_limits'])


if __name__ == '__main__': unittest.main()
