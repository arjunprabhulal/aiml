import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from consolidate import consolidate, plan
from memory import Clock, MemoryInputError, MemoryNotFound, MemoryStore, Scope, STEPS

HERE = Path(__file__).parent
ALICE = Scope('alice', 'trip-planning')


class ConsolidationTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = str(Path(folder.name) / 'memory.sqlite3')
        self.clock = Clock()
        self.store = MemoryStore(self.path, self.clock)
        self.addCleanup(self.store.close)

    def fact(self, text, attribute=None, authority='user', scope=ALICE, level='user', **options):
        return self.store.remember(scope, level, text, 'turn-1', attribute=attribute, authority=authority, **options)

    def texts(self, scope=ALICE):
        return [row['text'] for row in self.store.current(scope)]

    def test_fixture_matches_recorded_result(self):
        output = subprocess.run([sys.executable, 'demo.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'consolidation-result.json').read_text()))

    def test_user_statement_beats_a_newer_inference(self):
        stated = self.fact('Alice is vegetarian.', 'diet')
        inferred = self.fact('Alice eats meat.', 'diet', authority='inferred')
        report = consolidate(self.store, ALICE)
        self.assertEqual(report['resolved'], [{'kept': stated, 'retired': inferred,
                                               'rule': 'user statement over inference'}])
        self.assertEqual(self.texts(), ['Alice is vegetarian.'])

    def test_duplicate_of_an_inference_keeps_the_users_statement(self):
        inferred = self.fact('Alice is vegetarian.', 'diet', authority='inferred')
        stated = self.fact('Alice is vegetarian.', 'diet')
        newer_inference = self.fact('Alice eats fish.', 'diet', authority='inferred')
        report = consolidate(self.store, ALICE)
        self.assertEqual(report['resolved'], [
            {'kept': stated, 'retired': inferred, 'rule': 'duplicate'},
            {'kept': stated, 'retired': newer_inference, 'rule': 'user statement over inference'}])
        self.assertEqual(self.texts(), ['Alice is vegetarian.'])

    def test_restating_an_earlier_value_makes_it_current(self):
        first = self.fact('Alice prefers aisle seats.', 'seat')
        window = self.fact('Alice prefers window seats.', 'seat')
        again = self.fact('Alice prefers aisle seats.', 'seat')
        report = consolidate(self.store, ALICE)
        self.assertEqual(report['resolved'], [
            {'kept': first, 'retired': window, 'rule': 'newer statement'},
            {'kept': first, 'retired': again, 'rule': 'duplicate'}])
        self.assertEqual(self.texts(), ['Alice prefers aisle seats.'])
        self.assertEqual([r['source'] for r in self.store.current(ALICE)], ['turn-1'])

    def test_newer_statement_wins_and_the_older_stays_stored(self):
        older = self.fact('Alice prefers aisle seats.', 'seat')
        newer = self.fact('Alice prefers window seats now.', 'seat')
        consolidate(self.store, ALICE)
        self.assertEqual(self.texts(), ['Alice prefers window seats now.'])
        self.assertEqual(self.store.resolutions(ALICE)[0]['retired'], older)
        self.assertEqual(self.store.resolutions(ALICE)[0]['kept'], newer)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM memories').fetchone()[0], 2)

    def test_duplicate_keeps_the_first_source(self):
        first = self.store.remember(ALICE, 'user', 'Alice flies from Lisbon.', 'turn-7', attribute='home-airport')
        self.store.remember(ALICE, 'user', '  alice flies from LISBON ', 'turn-40', attribute='home-airport')
        report = consolidate(self.store, ALICE)
        self.assertEqual(report['resolved'][0]['rule'], 'duplicate')
        self.assertEqual([r['source'] for r in self.store.current(ALICE)], ['turn-7'])
        self.assertEqual(report['resolved'][0]['kept'], first)

    def test_second_run_changes_nothing(self):
        self.fact('Alice prefers aisle seats.', 'seat')
        self.fact('Alice prefers window seats now.', 'seat')
        consolidate(self.store, ALICE)
        self.assertEqual(consolidate(self.store, ALICE)['resolved'], [])
        self.assertEqual(len(self.store.resolutions(ALICE)), 1)

    def test_free_text_contradiction_is_not_detected(self):
        a = self.fact('Alice dislikes noisy hotels.')
        b = self.fact('Alice does not mind noise in hotels.')
        report = consolidate(self.store, ALICE)
        self.assertEqual(report['resolved'], [])
        self.assertEqual(report['facts_without_attribute'], [a, b])
        self.assertEqual(len(self.texts()), 2)

    def test_task_fact_overrides_only_inside_its_task(self):
        self.fact('Alice is vegetarian.', 'diet')
        porto = Scope('alice', 'porto-trip')
        self.fact('This week Alice is eating vegan.', 'diet', scope=porto, level='task')
        self.assertEqual(consolidate(self.store, porto)['resolved'], [])
        self.assertEqual(self.texts(porto), ['This week Alice is eating vegan.'])
        self.assertEqual(self.texts(ALICE), ['Alice is vegetarian.'])

    def test_resolve_writes_all_or_nothing(self):
        a = self.fact('Alice prefers aisle seats.', 'seat')
        b = self.fact('Alice prefers window seats now.', 'seat')
        with self.assertRaises(MemoryNotFound):
            self.store.resolve(ALICE, [(b, a, 'newer statement'), (b, 999, 'newer statement')])
        self.assertEqual(self.store.resolutions(ALICE), [])
        porto = Scope('alice', 'porto-trip')
        c = self.fact('Window seat for this trip.', 'seat', scope=porto, level='task')
        with self.assertRaisesRegex(MemoryInputError, 'same level'):
            self.store.resolve(porto, [(c, b, 'newer statement')])

    def test_forgetting_a_kept_fact_does_not_revive_the_retired_one(self):
        stated = self.fact('Alice is vegetarian.', 'diet')
        inferred = self.fact('Alice eats meat.', 'diet', authority='inferred')
        consolidate(self.store, ALICE)
        self.assertEqual(self.store.forget(ALICE, stated, 'user request'), [stated, inferred])
        self.assertEqual(self.texts(), [])
        self.assertEqual(self.store.resolutions(ALICE), [])

    def test_purging_an_expired_kept_fact_removes_what_it_retired(self):
        self.fact('Alice prefers aisle seats.', 'seat')
        self.fact('Alice prefers window seats this month.', 'seat', ttl_days=30)
        consolidate(self.store, ALICE)
        self.clock.advance(days=31)
        self.assertEqual(self.store.purge_expired(), 2)
        self.assertEqual(self.texts(), [])

    def test_corrected_facts_and_other_users_are_not_compared(self):
        old = self.fact('Alice is vegetarian.', 'diet')
        new = self.store.correct(ALICE, old, 'Alice eats fish but no meat.', 'turn-12')
        self.fact('Bob eats meat.', 'diet', scope=Scope('bob', 'trip-planning'))
        inferred = self.fact('Alice eats meat.', 'diet', authority='inferred')
        self.assertEqual(plan(self.store, ALICE), [(new, inferred, 'user statement over inference')])
        self.assertEqual(plan(self.store, Scope('bob', 'trip-planning')), [])

    def test_version_3_file_is_migrated(self):
        path = Path(self.path).with_name('v3.sqlite3')
        db = sqlite3.connect(path)
        db.execute('BEGIN')
        for step in (0, 1, 2):
            for statement in STEPS[step]:
                db.execute(statement)
        db.execute("INSERT INTO memories (user_id, kind, text, source, created_at) "
                   "VALUES ('alice', 'semantic', 'Alice is vegetarian.', 'turn-3', '2026-10-01T09:00:00+00:00')")
        db.execute('PRAGMA user_version = 3')
        db.commit()
        db.close()
        store = MemoryStore(str(path), self.clock)
        self.addCleanup(store.close)
        row = store.current(ALICE)[0]
        self.assertEqual((row['attribute'], row['authority'], row['source']), (None, 'user', 'turn-3'))
        with self.assertRaises(sqlite3.IntegrityError):
            with store.db:
                store.db.execute("INSERT INTO memories (user_id, kind, attribute, text, source, created_at, "
                                 "occurred_at) VALUES ('alice', 'episodic', 'diet', 'x', 's', 't', '2026-10-01')")

    def test_invalid_authority_or_attribute_is_rejected(self):
        for action in (lambda: self.fact('x', 'diet', authority='model'),
                       lambda: self.fact('x', 'Diet Type'),
                       lambda: self.store.remember(ALICE, 'user', 'x', 's', kind='episodic',
                                                   occurred_at='2026-10-01', attribute='diet')):
            with self.assertRaises(MemoryInputError):
                action()
        self.assertEqual(self.texts(), [])


if __name__ == '__main__':
    unittest.main()
