import unittest
import json
import tempfile
from pathlib import Path
from core import load
from curate_traces import curate, partition, redact, save


class CurationTests(unittest.TestCase):
    def test_a_family_cannot_cross_the_split(self):
        split = load('splits.json')
        split['test'].append(split['development'][0])
        with self.assertRaisesRegex(ValueError, 'more than one split'):
            partition(load('cases.json'), split)

    def test_relabelled_duplicates_are_rejected(self):
        cases = load('cases.json')
        cases.append({**cases[0], 'id': 'new-id', 'expected_doc': 'wrong-page'})
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            partition(cases, load('splits.json'))

    def test_renaming_an_exact_copy_does_not_add_a_case(self):
        cases = load('cases.json')
        cases.append({**cases[0], 'id': 'copy'})
        split = partition(cases, load('splits.json'))
        self.assertEqual(sum(map(len, split.values())), 18)

    def test_known_sensitive_patterns_are_removed(self):
        text = redact('Ask owner@example.invalid TOKEN=sample_secret')
        self.assertNotIn('example.invalid', text)
        self.assertNotIn('sample_secret', text)

    def test_unknown_family_cannot_silently_drop(self):
        cases = load('cases.json')
        cases[0]['family'] = 'unassigned'
        with self.assertRaisesRegex(ValueError, 'no assigned split'):
            partition(cases, load('splits.json'))

    def test_saved_trace_uses_redacted_question_before_policy_execution(self):
        cases = load('cases.json')
        cases[0]['question'] += ' owner@example.invalid TOKEN=sample_secret'
        records = curate(cases, load('splits.json'))
        with tempfile.TemporaryDirectory() as directory:
            save(records, directory)
            text = (Path(directory) / 'train.json').read_text()
            self.assertNotIn('owner@example.invalid', text)
            self.assertNotIn('sample_secret', text)
            rows = json.loads(text)
            changed = next(row for row in rows if row['case']['id'] == cases[0]['id'])
            query = changed['result']['trace'][0]['decision']['query']
            self.assertEqual(query, changed['case']['question'])
            self.assertIn('[email]', query)

    def test_deduplicated_case_has_only_one_executed_trace(self):
        cases = load('cases.json')
        cases.append({**cases[0], 'id': 'duplicate-id'})
        records = curate(cases, load('splits.json'))
        self.assertEqual(sum(map(len, records.values())), len(cases) - 1)


if __name__ == '__main__':
    unittest.main()
