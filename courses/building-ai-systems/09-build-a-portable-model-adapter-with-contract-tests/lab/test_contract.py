"""The adapter contract, run once per adapter, against recorded wire traffic. No model or network is used."""
import json
import socket
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import adapters as lab
from record_wire import CASES, MESSAGES, report

HERE = Path(__file__).resolve().parent
RECORD = json.loads((HERE / 'wire-record.json').read_text())
MODELS = sorted({row['model'] for row in RECORD['rows']})


def recorded(model, adapter, case):
    return next(r for r in RECORD['rows'] if (r['model'], r['adapter'], r['case']) == (model, adapter, case))


class Replay:
    """A post() that answers with one recorded or edited response and keeps what was sent."""

    def __init__(self, status, body):
        self.status, self.body, self.sent = status, body if isinstance(body, bytes) else body.encode(), []

    def __call__(self, url, payload, headers, timeout):
        self.sent.append((url, payload))
        return self.status, self.body


def never(*args):
    raise AssertionError('The adapter sent a request it should have refused.')


class Contract:
    """Every adapter must pass every test here. Subclasses only name the adapter and its wire shape."""
    adapter_class = None
    sets_context = None

    def make(self, post=never):
        return self.adapter_class(post=post)

    def replay(self, model, case):
        row = recorded(model, self.adapter_class.name, case)
        post = Replay(row['status'], row['body'])
        return post, row

    def test_a_completed_reply_is_normalized(self):
        for model in MODELS:
            with self.subTest(model=model):
                post, row = self.replay(model, 'complete')
                got = self.make(post).complete(model, CASES['complete'][1])
                self.assertEqual(post.sent[0][1], row['request'])
                self.assertEqual(got.finish, 'stop')
                self.assertTrue(got.text.startswith('HTTP stands for'))
                self.assertGreater(got.input_tokens, 0)
                self.assertGreater(got.output_tokens, 0)

    def test_the_output_limit_is_a_result_not_an_error(self):
        for model in MODELS:
            with self.subTest(model=model):
                post, _ = self.replay(model, 'output-limit')
                got = self.make(post).complete(model, CASES['output-limit'][1])
                self.assertEqual((got.finish, got.output_tokens), ('length', 3))

    def test_a_missing_model_is_model_not_found(self):
        post, _ = self.replay(MODELS[0], 'missing-model')
        with self.assertRaises(lab.AdapterError) as caught:
            self.make(post).complete('aiml-missing:never', CASES['missing-model'][1])
        self.assertEqual(caught.exception.kind, 'model_not_found')

    def test_thinking_is_turned_off_in_every_request(self):
        body = self.make().body('qwen3.5:0.8b', CASES['complete'][1])
        self.assertIn(body.get('think', body.get('reasoning_effort')), (False, 'none'))
        post, _ = self.replay('qwen3.5:0.8b', 'thinking-left-on')
        with self.assertRaises(lab.AdapterError) as caught:
            self.make(post).complete('qwen3.5:0.8b', CASES['complete'][1])
        self.assertEqual(caught.exception.kind, 'protocol')

    def test_server_errors_and_malformed_bodies_get_a_named_kind(self):
        good = json.loads(recorded(MODELS[0], self.adapter_class.name, 'complete')['body'])
        cases = [(500, good, 'http'), (400, {'error': 'bad request'}, 'http'), (200, b'{not json', 'protocol'),
                 (200, [], 'protocol')] + [(200, body, 'protocol') for body in self.broken(good)]
        for status, body, kind in cases:
            with self.subTest(status=status, body=str(body)[:70]):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                with self.assertRaises(lab.AdapterError) as caught:
                    self.make(Replay(status, raw)).complete(MODELS[0], CASES['complete'][1])
                self.assertEqual(caught.exception.kind, kind)

    def test_transport_failures_are_reported_once_without_retry(self):
        adapter = self.adapter_class()
        for error, kind in ((URLError(ConnectionRefusedError(61, 'refused')), 'connection'),
                            (URLError(socket.timeout('timed out')), 'timeout'), (TimeoutError(), 'timeout')):
            with self.subTest(kind=kind), patch.object(lab, 'urlopen', side_effect=error) as opened:
                with self.assertRaises(lab.AdapterError) as caught:
                    lab.http_post(adapter.base_url + adapter.path, {}, {}, 5)
                self.assertEqual((caught.exception.kind, opened.call_count), (kind, 1))

    def test_requests_are_checked_before_anything_is_sent(self):
        adapter = self.make()
        bad = [(), (('user', ' '),), (('assistant', 'Hi'),), (('user', 'a'), ('system', 'late'), ('user', 'b')),
               (('tool', 'x'), ('user', 'a')), [('user', 'not a tuple')]]
        for messages in bad:
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                adapter.complete('gemma4:e2b', lab.ChatRequest(messages))
        for change in ({'max_tokens': 0}, {'max_tokens': True}, {'temperature': 3}, {'temperature': '0'},
                       {'seed': 1.5}, {'context_tokens': 10}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                adapter.complete('gemma4:e2b', lab.ChatRequest(MESSAGES, **change))
        for origin in ('https://example.com', 'http://example.com:11434', 'http://localhost/v1'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                self.adapter_class(base_url=origin)

    def test_an_option_the_api_cannot_carry_is_refused_not_dropped(self):
        request = lab.ChatRequest(MESSAGES, context_tokens=4096)
        if self.sets_context:
            post, _ = self.replay(MODELS[0], 'complete')
            self.make(post).complete(MODELS[0], request)
            self.assertEqual(post.sent[0][1]['options']['num_ctx'], 4096)
        else:
            with self.assertRaises(lab.AdapterError) as caught:
                self.make().complete(MODELS[0], request)
            self.assertEqual(caught.exception.kind, 'unsupported')


class NativeContract(Contract, unittest.TestCase):
    adapter_class = lab.OllamaChatAdapter
    sets_context = True

    @staticmethod
    def broken(good):
        message = good['message']
        return [{**good, 'done': False}, {**good, 'message': {**message, 'role': 'user'}},
                {**good, 'message': {**message, 'content': ''}}, {**good, 'message': {**message, 'tool_calls': [{}]}},
                {**good, 'done_reason': 'unload'}, {**good, 'eval_count': -1}, {**good, 'prompt_eval_count': '26'}]


class CompatibleContract(Contract, unittest.TestCase):
    adapter_class = lab.OpenAICompatibleAdapter
    sets_context = False

    @staticmethod
    def broken(good):
        choice, message = good['choices'][0], good['choices'][0]['message']
        return [{**good, 'choices': []}, {**good, 'choices': [choice, choice]},
                {**good, 'choices': [{**choice, 'message': {**message, 'content': ''}}]},
                {**good, 'choices': [{**choice, 'message': {**message, 'tool_calls': [{}]}}]},
                {**good, 'choices': [{**choice, 'finish_reason': 'content_filter'}]},
                {**good, 'usage': None}, {**good, 'usage': {**good['usage'], 'completion_tokens': -1}}]


class RecordedComparison(unittest.TestCase):
    def test_the_report_is_reproduced_from_the_recording(self):
        expected = (HERE / 'contract-report.json').read_text()
        self.assertEqual(json.dumps(report(RECORD), indent=2, ensure_ascii=False) + '\n', expected)

    def test_both_wire_formats_give_the_same_result_for_every_recorded_case(self):
        for model, cases in report(RECORD).items():
            for case, outcomes in cases.items():
                with self.subTest(model=model, case=case):
                    self.assertTrue(outcomes['agree'])


if __name__ == '__main__':
    unittest.main()
