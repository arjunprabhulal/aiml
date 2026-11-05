"""Offline tests for the retrieval answer check. They grade recorded answers; no model is called."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from answer_check import KEYS, grade
from answer_model import MODEL, AnswerModel, AnswerModelError

HERE = Path(__file__).parent
HOTEL, FOOD = list(KEYS)


def answer(text=''):
    return {'seed': 1, 'answer': text, 'tool_calls': [], 'done_reason': 'stop'}


class AnswerCheckTest(unittest.TestCase):
    def test_recorded_answers_grade_as_recorded(self):
        output = subprocess.run([sys.executable, 'answer_check.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'answer-grades.json').read_text()))

    def test_keys_match_the_scenario_questions(self):
        scenario = json.loads((HERE / 'scenario.json').read_text())
        self.assertEqual(list(KEYS), [q['query'] for q in scenario['queries']])

    def test_answer_without_dates_and_budget_fails(self):
        self.assertEqual(grade(HOTEL, answer('Alice prefers a hotel near a river.')),
                         ('fail', 'missing: trip dates, budget'))
        self.assertEqual(grade(HOTEL, answer('3 to 6 November, 150 euros a night, near the river.'))[0], 'pass')

    def test_replaced_fact_stated_as_current_fails(self):
        self.assertEqual(grade(FOOD, answer('Alice is vegetarian, so order fish.'))[0], 'fail')
        self.assertEqual(grade(FOOD, answer('She eats fish but no meat, so she is not vegetarian.'))[0], 'pass')

    def test_empty_answer_is_incomplete(self):
        self.assertEqual(grade(FOOD, answer(' ')), ('incomplete', 'no answer'))

    def test_unpinned_model_is_refused(self):
        def transport(path, payload):
            return {'models': [{'name': MODEL['ollama_tag'], 'digest': 'other'}]}
        with self.assertRaisesRegex(AnswerModelError, 'pinned digest'):
            AnswerModel(transport)


if __name__ == '__main__':
    unittest.main()
