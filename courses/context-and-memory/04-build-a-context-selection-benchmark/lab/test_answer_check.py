"""Offline tests for the strategy answer check. They grade recorded answers; no model is called."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from answer_check import KEYS, grade
from answer_model import MODEL, AnswerModel, AnswerModelError

HERE = Path(__file__).parent


def answer(text=''):
    return {'seed': 1, 'answer': text, 'tool_calls': [], 'done_reason': 'stop'}


class AnswerCheckTest(unittest.TestCase):
    def test_recorded_answers_grade_as_recorded(self):
        output = subprocess.run([sys.executable, 'answer_check.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'answer-grades.json').read_text()))

    def test_keys_cover_exactly_the_held_out_cases(self):
        cases = json.loads((HERE / 'cases.json').read_text())
        self.assertEqual(set(KEYS), {c['id'] for c in cases if c['split'] == 'held_out'})

    def test_replaced_decision_presented_as_current_fails(self):
        self.assertEqual(grade('held-correction', answer('We decided to use RabbitMQ for the job queue.')),
                         ('fail', 'presents a replaced decision as current'))
        self.assertEqual(grade('held-correction', answer('Redis streams, not RabbitMQ.'))[0], 'pass')

    def test_every_required_fact_is_needed(self):
        self.assertEqual(grade('held-spread', answer('Passwords need at least 14 characters.'))[0], 'fail')
        self.assertEqual(grade('held-spread', answer('At least 14 characters; sessions expire after 30 minutes.'))[0], 'pass')

    def test_saying_a_fact_is_missing_is_a_counted_fail(self):
        self.assertEqual(grade('held-old-decision', answer('I do not have information about where uploads are stored.')),
                         ('fail', 'says the fact is missing'))
        self.assertEqual(grade('held-old-decision', answer('')), ('incomplete', 'no answer'))

    def test_unpinned_model_is_refused(self):
        def transport(path, payload):
            return {'models': [{'name': MODEL['ollama_tag'], 'digest': 'other'}]}
        with self.assertRaisesRegex(AnswerModelError, 'pinned digest'):
            AnswerModel(transport)


if __name__ == '__main__':
    unittest.main()
