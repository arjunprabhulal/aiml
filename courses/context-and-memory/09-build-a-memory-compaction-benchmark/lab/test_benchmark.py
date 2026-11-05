import json
from pathlib import Path
import subprocess
import sys
import unittest
import benchmark
from generate_conversation import conversation

HERE = Path(__file__).parent


def recorded():
    return json.loads((HERE / 'benchmark-result.json').read_text())


_LIVE = {}


def live():
    """Run the benchmark in this process, so each test checks the code, not only the recording."""
    if not _LIVE:
        _LIVE.update(benchmark.full_report(case()))
    return _LIVE


def case():
    return json.loads((HERE / 'conversation.json').read_text())


class BenchmarkTest(unittest.TestCase):
    def test_fixture_matches_recorded_result(self):
        output = subprocess.run([sys.executable, 'benchmark.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        fresh, record = json.loads(output), recorded()
        # The Python and SQLite versions describe the run, not the result.
        self.assertEqual(set(record.pop('environment')), {'python', 'sqlite'})
        fresh.pop('environment')
        self.assertEqual(fresh, record)

    def test_conversation_matches_its_generator(self):
        self.assertEqual(case(), conversation())
        self.assertEqual(len(case()['turns']), 50)

    def test_every_checked_fact_was_said_before_its_checkpoint(self):
        data = case()
        for checkpoint in data['checkpoints']:
            said = ' '.join(t['user'] for t in data['turns'] if t['turn'] <= checkpoint['after'])
            for fact in checkpoint['required'] + checkpoint['stale'] + checkpoint['deleted']:
                with self.subTest(after=checkpoint['after'], fact=fact):
                    self.assertIn(fact, said)

    def test_every_request_fits_the_budget(self):
        report = live()
        for name, rows in report['checkpoints'].items():
            for row in rows:
                with self.subTest(strategy=name, after=row['after']):
                    self.assertLessEqual(row['input_tokens'], report['input_budget'])

    def test_managed_memory_never_sends_stale_or_forgotten_facts(self):
        report = live()
        for row in report['checkpoints']['managed']:
            self.assertEqual((row['stale'], row['deleted']), ([], []), row['after'])
        for totals in report['quota_sweep'].values():
            self.assertEqual((totals['managed']['stale'], totals['managed']['deleted']), (0, 0))

    def test_managed_request_omits_a_fact_forgotten_one_turn_earlier(self):
        data = case()
        turns = [t for t in data['turns'] if t['turn'] <= 12]
        turns.append({'turn': 13, 'user': 'Please forget my passport number.', 'assistant': 'Noted.',
                      'memory': {'op': 'forget', 'attribute': 'passport'}})
        checkpoint = {'after': 13, 'question': 'Summarize the trip plan so far.', 'required': [], 'stale': [],
                      'deleted': ['P1234567']}
        report = benchmark.run({**data, 'turns': turns, 'checkpoints': [checkpoint]})
        leaks = {name: rows[0]['deleted'] for name, rows in report['checkpoints'].items()}
        self.assertEqual(leaks['managed'], [])
        # The other strategies send the raw transcript, so the number is still in their recent turns.
        self.assertEqual([name for name, found in leaks.items() if found], ['recent', 'notes', 'append-only'])

    def test_append_only_memory_leaks_the_forgotten_fact(self):
        report = live()
        at_40 = next(r for r in report['checkpoints']['append-only'] if r['after'] == 40)
        self.assertEqual(at_40['deleted'], ['P1234567'])
        sweep = report['quota_sweep']
        self.assertGreater(sweep['240']['append-only']['deleted'], sweep['160']['append-only']['deleted'])
        self.assertGreater(sweep['240']['append-only']['stale'], sweep['160']['append-only']['stale'])

    def test_recent_turns_lose_early_facts(self):
        at_50 = next(r for r in live()['checkpoints']['recent'] if r['after'] == 50)
        self.assertEqual(at_50['found'], 0)
        self.assertIn('going to Porto', at_50['missing'])

    def test_cue_extraction_finds_none_of_these_facts(self):
        facts = [t['user'] for t in case()['turns'] if 'memory' in t]
        self.assertEqual([f for f in facts if benchmark.CUES.search(f)], [])
        self.assertLessEqual(live()['totals']['notes']['found'], live()['totals']['recent']['found'])

    def test_a_small_facts_quota_drops_the_oldest_current_fact(self):
        report = live()
        self.assertEqual(report['facts_quota'], 160)
        self.assertEqual(report['totals']['managed']['found'], report['totals']['managed']['required'])
        small = benchmark.run(case(), 120)
        at_50 = next(r for r in small['checkpoints']['managed'] if r['after'] == 50)
        self.assertEqual(at_50['missing'], ['going to Porto'])
        self.assertEqual(small['totals']['managed'], report['quota_sweep']['120']['managed'])

    def test_forgotten_fact_is_gone_from_the_managed_store(self):
        storage = live()['storage']
        self.assertEqual(storage['managed']['deletion_records'], 1)
        self.assertEqual(storage['append-only']['deletion_records'], 0)
        self.assertLess(storage['managed']['current_facts'], storage['append-only']['current_facts'])


if __name__ == '__main__':
    unittest.main()
