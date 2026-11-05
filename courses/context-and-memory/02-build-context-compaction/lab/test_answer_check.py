"""Offline tests for the compaction answer check. They grade recorded answers; no model is called."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from answer_check import grade, stale_mysql
from answer_model import MODEL, AnswerModel, AnswerModelError

HERE = Path(__file__).parent


def answer(text='', tool_calls=()):
    return {'seed': 1, 'answer': text, 'tool_calls': list(tool_calls), 'done_reason': 'stop'}


class AnswerCheckTest(unittest.TestCase):
    def test_recorded_answers_grade_as_recorded(self):
        output = subprocess.run([sys.executable, 'answer_check.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'answer-grades.json').read_text()))

    def test_replaced_decision_presented_as_current_fails(self):
        text = '* For the first version we will use MySQL.\n* Exports must finish within 15 minutes.'
        self.assertEqual(stale_mysql(text), 1)
        self.assertEqual(grade(answer(text)), ('fail', 'presents MySQL as current'))

    def test_replaced_decision_named_as_replaced_passes(self):
        text = 'The application uses PostgreSQL, which replaced MySQL. Exports must finish within 15 minutes.'
        self.assertEqual(grade(answer(text))[0], 'pass')

    def test_answer_missing_a_decision_fails(self):
        self.assertEqual(grade(answer('Exports must finish within 15 minutes.')), ('fail', 'leaves out PostgreSQL'))

    def test_empty_answer_is_incomplete(self):
        self.assertEqual(grade(answer(''))[0], 'incomplete')

    def test_unpinned_model_is_refused(self):
        def transport(path, payload):
            return {'models': [{'name': MODEL['ollama_tag'], 'digest': 'other'}]}
        with self.assertRaisesRegex(AnswerModelError, 'pinned digest'):
            AnswerModel(transport)


if __name__ == '__main__':
    unittest.main()
