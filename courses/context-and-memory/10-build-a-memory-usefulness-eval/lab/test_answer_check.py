"""Offline tests for the usefulness answer check. They grade recorded answers; no model is called."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from answer_check import KEYS, grade
from answer_model import MODEL, AnswerModel, AnswerModelError

HERE = Path(__file__).parent
PASSPORT = 'Can you fill in my passport number on the form?'
DATABASE = 'Which database does the billing service use?'
DESK = 'Who approves my desk order?'


def answer(text=''):
    return {'seed': 1, 'answer': text, 'tool_calls': [], 'done_reason': 'stop'}


class AnswerCheckTest(unittest.TestCase):
    def test_recorded_answers_grade_as_recorded(self):
        output = subprocess.run([sys.executable, 'answer_check.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'answer-grades.json').read_text()))

    def test_keys_match_the_case_questions(self):
        cases = json.loads((HERE / 'cases.json').read_text())
        self.assertEqual(list(KEYS), [q['question'] for c in cases['conversations'] for q in c['questions']])

    def test_forgotten_fact_in_the_answer_fails(self):
        self.assertEqual(grade(PASSPORT, answer('Your passport number is P1234567.')),
                         ('fail', 'states a forgotten fact'))
        self.assertEqual(grade(PASSPORT, answer('I have no passport number stored.')), ('pass', 'leaks nothing'))

    def test_replaced_fact_stated_as_current_fails(self):
        self.assertEqual(grade(DATABASE, answer('It uses PostgreSQL.')), ('fail', 'states a replaced fact as current'))
        self.assertEqual(grade(DATABASE, answer('Billing moved to MySQL, not PostgreSQL.'))[0], 'pass')

    def test_answer_without_the_required_fact_fails(self):
        question = 'What is the budget per night for the hotel?'
        self.assertEqual(grade(question, answer('I have no budget notes.')), ('fail', 'missing: 180 euros'))
        self.assertEqual(grade(question, answer('The budget is 180 euros per night.'))[0], 'pass')

    def test_empty_answer_is_incomplete(self):
        self.assertEqual(grade(DESK, answer(' ')), ('incomplete', 'no answer'))

    def test_unpinned_model_is_refused(self):
        def transport(path, payload):
            return {'models': [{'name': MODEL['ollama_tag'], 'digest': 'other'}]}
        with self.assertRaisesRegex(AnswerModelError, 'pinned digest'):
            AnswerModel(transport)


if __name__ == '__main__':
    unittest.main()
