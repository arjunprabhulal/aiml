import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import evaluate
from generate_cases import cases
from memory import Clock, MemoryStore, Scope, words

HERE = Path(__file__).parent
_LIVE = {}


def fixture():
    return json.loads((HERE / 'cases.json').read_text())


def live():
    """Run the evaluation in this process, so each test checks the code, not only the recording."""
    if not _LIVE:
        _LIVE.update(evaluate.run(fixture()))
    return _LIVE


class EvaluationTest(unittest.TestCase):
    def test_fixture_matches_recorded_result(self):
        output = subprocess.run([sys.executable, 'evaluate.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        fresh = json.loads(output)
        recorded = json.loads((HERE / 'evaluation-result.json').read_text())
        # Python and SQLite versions and file sizes describe the run, not the result.
        self.assertEqual(set(recorded.pop('environment')), {'python', 'sqlite', 'file_bytes_after_replay'})
        fresh.pop('environment')
        self.assertEqual(fresh, recorded)

    def test_cases_match_their_generator(self):
        self.assertEqual(fixture(), cases())

    def test_every_listed_fact_was_said_by_that_user(self):
        for conversation in fixture()['conversations']:
            said = ' '.join(e['text'] for e in conversation['events'])
            for question in conversation['questions']:
                for fact in question['required'] + question['stale'] + question['forgotten']:
                    with self.subTest(user=conversation['user'], fact=fact):
                        self.assertIn(fact, said)

    def test_managed_memory_sends_no_stale_or_forgotten_lines(self):
        for name in ('managed-all', 'managed-relevant'):
            summary = live()['summary'][name]
            self.assertEqual((summary['stale_lines'], summary['forgotten_lines']), (0, 0), name)

    def test_append_only_memory_sends_stale_and_forgotten_lines(self):
        summary = live()['summary']['append-all']
        self.assertGreater(summary['stale_lines'], 0)
        self.assertGreater(summary['forgotten_lines'], 0)
        leaks = [q['question'] for q in live()['questions']['append-all'] if q['forgotten']]
        self.assertIn('Can you fill in my passport number on the form?', leaks)

    def test_relevance_trades_recall_for_usefulness(self):
        everything, matched = live()['summary']['managed-all'], live()['summary']['managed-relevant']
        self.assertEqual(everything['recall'], 1.0)
        self.assertLess(matched['recall'], everything['recall'])
        self.assertGreater(matched['usefulness'], everything['usefulness'])
        self.assertLess(matched['memory_tokens'], everything['memory_tokens'])

    def test_relevance_misses_only_facts_without_shared_words(self):
        conversations = {c['user']: c for c in fixture()['conversations']}
        for row in live()['questions']['managed-relevant']:
            said = [e['text'] for e in conversations[row['user']]['events']]
            for fact in row['missing']:
                sentence = next(text for text in reversed(said) if fact in text)
                with self.subTest(question=row['question'], fact=fact):
                    self.assertEqual(words(row['question']) & words(sentence), set())

    def test_memory_block_stays_within_the_quota(self):
        quota = live()['facts_quota']
        for name, rows in live()['questions'].items():
            for row in rows:
                with self.subTest(strategy=name, question=row['question']):
                    self.assertLessEqual(row['memory_tokens'], quota)

    def test_managed_storage_keeps_history_and_deletes_forgotten_facts(self):
        growth = live()['growth']
        managed, append = growth['managed'], growth['append']
        self.assertEqual([g['stored_rows'] for g in append], [g['current_facts'] for g in append])
        for row in managed:
            self.assertLess(row['current_facts'], row['stored_rows'])
        superseded = [g['superseded_rows'] for g in managed]
        self.assertEqual(superseded, sorted(superseded))
        forgets = sum(1 for e in fixture()['long_replay']['events'] if e['op'] == 'forget')
        self.assertEqual(managed[-1]['deletion_records'], forgets)
        self.assertLess(managed[-1]['current_facts'], append[-1]['current_facts'])

    def test_forgotten_note_text_is_not_stored(self):
        replay = fixture()['long_replay']
        scope = Scope(replay['user'], 'assistant')
        with tempfile.TemporaryDirectory() as folder:
            store = MemoryStore(str(Path(folder) / 'm.sqlite3'), Clock())
            for event in replay['events']:
                evaluate.apply(store, scope, event, managed=True)
            texts = [r[0] for r in store.db.execute('SELECT text FROM memories')]
            store.close()
        for event in replay['events']:
            if event['op'] == 'forget':
                number = event['attribute'].split('-')[1]
                self.assertFalse([t for t in texts if t.startswith(f'Note {number}:')], event['text'])


if __name__ == '__main__':
    unittest.main()
