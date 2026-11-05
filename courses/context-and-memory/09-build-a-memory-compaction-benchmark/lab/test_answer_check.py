"""Offline tests for the benchmark answer check. They grade recorded answers; no model is called."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from answer_check import KEYS, checkpoints, grade
from answer_model import MODEL, AnswerModel, AnswerModelError

HERE = Path(__file__).parent
AT_40 = checkpoints()[40]
CURRENT = ('Porto, 10 to 13 November, 180 euros per night, a hotel near the river, '
           'the morning flight, and she eats fish now.')


def answer(text='', done_reason='stop'):
    return {'seed': 1, 'answer': text, 'tool_calls': [], 'done_reason': done_reason}


class AnswerCheckTest(unittest.TestCase):
    def test_recorded_answers_grade_as_recorded(self):
        output = subprocess.run([sys.executable, 'answer_check.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'answer-grades.json').read_text()))

    def test_keys_cover_every_checkpoint_fact(self):
        for checkpoint in checkpoints().values():
            for kind in ('required', 'stale', 'deleted'):
                self.assertLessEqual(set(checkpoint[kind]), set(KEYS[kind]))

    def test_current_facts_pass(self):
        self.assertEqual(grade(AT_40, answer(CURRENT)), ('pass', 'every required fact'))

    def test_replaced_dates_stated_as_current_fail(self):
        stale = CURRENT + ' The trip is planned from November 3rd to November 6th.'
        self.assertEqual(grade(AT_40, answer(stale)), ('fail', 'states a replaced fact as current: 3 to 6 November'))
        marked = CURRENT + ' The dates were changed from 3 to 6 November.'
        self.assertEqual(grade(AT_40, answer(marked))[0], 'pass')

    def test_forgotten_passport_fails(self):
        self.assertEqual(grade(AT_40, answer(CURRENT + ' Passport: P1234567.')),
                         ('fail', 'sends the forgotten passport number'))

    def test_cut_off_answer_names_the_limit(self):
        cut = 'Porto, 10 to 13 November, 180 euros per night, a hotel near the river, the morning'
        self.assertEqual(grade(AT_40, answer(cut, 'length')),
                         ('fail', 'missing 1 of 6 required facts; stopped at the answer-token limit'))

    def test_empty_answer_is_incomplete(self):
        self.assertEqual(grade(AT_40, answer(' ')), ('incomplete', 'no answer'))

    def test_unpinned_model_is_refused(self):
        def transport(path, payload):
            return {'models': [{'name': MODEL['ollama_tag'], 'digest': 'other'}]}
        with self.assertRaisesRegex(AnswerModelError, 'pinned digest'):
            AnswerModel(transport)


if __name__ == '__main__':
    unittest.main()
