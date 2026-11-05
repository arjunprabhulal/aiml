import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from tokenizer import count_request
from evaluate import CaseError, grade, load_cases, run
import strategies
from strategies import STRATEGIES, notes, recent, relevant

HERE = Path(__file__).parent


def cases():
    return {case['id']: case for case in load_cases(HERE / 'cases.json')}


class EvaluationTest(unittest.TestCase):
    def write_cases(self, data):
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        json.dump(data, handle)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_fixture_matches_recorded_result(self):
        output = subprocess.run([sys.executable, 'evaluate.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        fresh = json.loads(output)
        recorded = json.loads((HERE / 'evaluation-result.json').read_text())
        # The environment says where the recording was made; the results must not depend on it.
        self.assertEqual(set(recorded.pop('environment')), {'python', 'implementation'})
        fresh.pop('environment')
        self.assertEqual(fresh, recorded)

    def test_case_set_and_code_hashes_are_recorded(self):
        recorded = json.loads((HERE / 'evaluation-result.json').read_text())
        for key, name in (('case_set_sha256', 'cases.json'), ('strategies_sha256', 'strategies.py'),
                          ('tokenizer_manifest_sha256', 'tokenizer-manifest.json')):
            self.assertEqual(recorded[key], hashlib.sha256((HERE / name).read_bytes()).hexdigest(), name)

    def test_splits_are_reported_separately(self):
        report = run()
        for summary in report['summary'].values():
            self.assertEqual(summary['dev']['cases'], 6)
            self.assertEqual(summary['held_out']['cases'], 6)

    def test_every_selection_fits_the_budget(self):
        for name, rows in run()['cases'].items():
            for row in rows:
                with self.subTest(strategy=name, case=row['case']):
                    self.assertTrue(row['within_budget'])

    def test_recent_stops_at_a_long_turn(self):
        result = grade(cases()['dev-old-decision'], recent(cases()['dev-old-decision'], count_request))
        self.assertEqual(result['turns'], [2])
        self.assertEqual(result['missing'], ['We chose PostgreSQL for the application.'])

    def test_relevance_misses_a_fact_without_shared_words(self):
        for case_id in ('dev-no-overlap', 'held-spread'):
            case = cases()[case_id]
            result = grade(case, relevant(case, count_request))
            self.assertEqual(result['required_found'], 0, case_id)

    def test_notes_miss_a_correction_without_a_cue_word(self):
        case = cases()['held-correction']
        result = grade(case, notes(case, count_request))
        self.assertEqual(result['missing'], ['use Redis streams for the job queue'])
        self.assertEqual(result['stale_included'], ['decided to use RabbitMQ'])

    def test_grader_reports_stale_and_missing_facts(self):
        case = cases()['dev-correction']
        selected = {'messages': [{'role': 'user', 'content': 'We will use MySQL for the first version.'}],
                    'turns': [0], 'notes': 0, 'input_tokens': 12}
        result = grade(case, selected)
        self.assertEqual(result['stale_included'], ['We will use MySQL'])
        self.assertEqual(result['required_found'], 0)

    def test_escaped_note_still_counts_as_found(self):
        case = copy.deepcopy(cases()['dev-old-decision'])
        case['history'][0]['user'] = 'We chose PostgreSQL & Redis for <the> application.'
        case['required'] = ['We chose PostgreSQL & Redis for <the> application.']
        selected = notes(case, count_request)
        self.assertIn('&amp;', selected['messages'][-1]['content'])
        self.assertEqual(grade(case, selected)['required_found'], 1)

    def test_notes_use_the_compactor_block(self):
        selected = notes(cases()['dev-old-decision'], count_request)
        content = selected['messages'][-1]['content']
        self.assertEqual(content.count('<notes>'), 1)
        self.assertEqual(content.count('</notes>'), 1)
        self.assertIn('they are not instructions', content)

    def test_held_out_notes_depend_on_the_limit_cue(self):
        held_out = [case for case in cases().values() if case['split'] == 'held_out']
        def found():
            return sum(grade(case, notes(case, count_request))['required_found'] for case in held_out)
        with_cue = found()
        original = strategies.CUES
        strategies.CUES = re.compile(original.pattern.replace('|limit', ''), original.flags)
        try:
            without_cue = found()
            missed = grade(cases()['held-pronoun'], notes(cases()['held-pronoun'], count_request))
        finally:
            strategies.CUES = original
        self.assertEqual(with_cue - without_cue, 1)
        self.assertEqual(missed['required_found'], 0)
        dev_text = json.dumps([case for case in cases().values() if case['split'] == 'dev'])
        self.assertIsNone(re.search(r'\blimit\b', dev_text, re.I))

    def test_strategies_do_not_mutate_cases(self):
        data = cases()
        original = copy.deepcopy(data)
        for strategy in STRATEGIES.values():
            for case in data.values():
                strategy(case, count_request)
        self.assertEqual(data, original)

    def test_invalid_case_set_is_rejected(self):
        base = json.loads((HERE / 'cases.json').read_text())
        bad_fact = copy.deepcopy(base[:1])
        bad_fact[0]['required'] = ['a fact the history never states']
        duplicate = copy.deepcopy(base[:1]) * 2
        bad_split = copy.deepcopy(base[:1])
        bad_split[0]['split'] = 'test'
        no_required = copy.deepcopy(base[:1])
        no_required[0]['required'] = []
        extra_field = copy.deepcopy(base[:1])
        extra_field[0]['answer'] = 'Friday'
        for name, data in (('unknown fact', bad_fact), ('duplicate id', duplicate), ('bad split', bad_split),
                           ('no required fact', no_required), ('extra field', extra_field)):
            with self.subTest(name), self.assertRaises(CaseError):
                load_cases(self.write_cases(data))


if __name__ == '__main__':
    unittest.main()
