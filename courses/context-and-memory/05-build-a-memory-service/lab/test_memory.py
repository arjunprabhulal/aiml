import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import memory
from memory import MemoryInputError, MemoryStore, SchemaError, Scope, fixed_clock

HERE = Path(__file__).parent
ALICE = Scope('alice', 'trip-planning')
BOB = Scope('bob', 'onboarding')


class MemoryServiceTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = str(Path(folder.name) / 'memory.sqlite3')

    def open(self):
        store = MemoryStore(self.path, clock=fixed_clock())
        self.addCleanup(store.close)
        return store

    def test_fixture_matches_recorded_result(self):
        output = subprocess.run([sys.executable, 'demo.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'memory-result.json').read_text()))

    def test_memories_survive_a_restart(self):
        store = MemoryStore(self.path, clock=fixed_clock())
        store.remember(ALICE, 'user', 'Alice is vegetarian.', 'turn-3')
        store.close()
        reopened = self.open()
        self.assertEqual([m['text'] for m in reopened.recall(ALICE, 'Is my meal vegetarian?')],
                         ['Alice is vegetarian.'])

    def test_another_users_memories_are_never_recalled(self):
        store = self.open()
        store.remember(ALICE, 'user', 'Book the Lisbon hotel near the river.', 'turn-5')
        self.assertEqual(store.recall(Scope('bob', 'trip-planning'), 'Which Lisbon hotel?'), [])
        self.assertEqual(store.count(BOB), 0)

    def test_task_memories_stay_in_their_task(self):
        store = self.open()
        store.remember(ALICE, 'task', 'Book the Lisbon hotel near the river.', 'turn-5')
        store.remember(ALICE, 'user', 'Alice prefers aisle seats on flights.', 'turn-6')
        other_task = Scope('alice', 'conference-trip')
        self.assertEqual(store.recall(other_task, 'Which Lisbon hotel?'), [])
        self.assertEqual(len(store.recall(other_task, 'Which seats on flights?')), 1)

    def test_every_memory_query_filters_by_user(self):
        statements = []
        store = self.open()
        store.db.set_trace_callback(statements.append)
        store.remember(ALICE, 'user', 'Alice is vegetarian.', 'turn-3')
        store.recall(ALICE, 'vegetarian')
        store.count(ALICE)
        touching = [s for s in statements if 'memories' in s]
        self.assertTrue(touching)
        for statement in touching:
            self.assertTrue(statement.startswith('INSERT') or 'WHERE user_id = ' in statement, statement)

    def test_text_is_stored_as_data_not_sql(self):
        store = self.open()
        text = "Robert'); DROP TABLE memories;--"
        store.remember(ALICE, 'user', text, 'turn-9')
        self.assertEqual(store.recall(ALICE, 'Robert drop table')[0]['text'], text)
        self.assertEqual(store.count(ALICE), 1)

    def test_unknown_schema_version_is_refused(self):
        self.open().close()
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA user_version = 2')
        db.close()
        with self.assertRaisesRegex(SchemaError, 'version 2'):
            MemoryStore(self.path)

    def test_failed_creation_leaves_an_empty_file(self):
        original = memory.SCHEMA
        memory.SCHEMA = original + ';\nTHIS IS NOT SQL'
        try:
            with self.assertRaises(sqlite3.OperationalError):
                MemoryStore(self.path)
        finally:
            memory.SCHEMA = original
        db = sqlite3.connect(self.path)
        self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0], 0)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
        db.close()
        self.open().remember(ALICE, 'user', 'Alice is vegetarian.', 'turn-3')

    def test_foreign_database_is_refused(self):
        db = sqlite3.connect(self.path)
        db.execute('CREATE TABLE notes (body TEXT)')
        db.close()
        with self.assertRaises(SchemaError):
            MemoryStore(self.path)

    def test_recall_orders_by_shared_words_then_newest(self):
        store = self.open()
        first = store.remember(ALICE, 'user', 'Alice likes window seats.', 'turn-1')
        second = store.remember(ALICE, 'user', 'Alice likes aisle seats now.', 'turn-2')
        store.remember(ALICE, 'user', 'Alice is vegetarian.', 'turn-3')
        recalled = store.recall(ALICE, 'Which seats does Alice like?', limit=5)
        self.assertEqual([m['id'] for m in recalled], [second, first, 3])
        self.assertEqual([m['score'] for m in recalled], [2, 2, 1])
        self.assertEqual(store.recall(ALICE, 'weather forecast'), [])

    def test_invalid_input_is_rejected_before_writing(self):
        store = self.open()
        for args in ((ALICE, 'global', 'text', 'turn-1'), (ALICE, 'user', '   ', 'turn-1'),
                     (ALICE, 'user', 'x' * 2001, 'turn-1'), (ALICE, 'user', 'text', ' ')):
            with self.subTest(args=args[1:3]), self.assertRaises(MemoryInputError):
                store.remember(*args)
        for user, task in (('', 'trip'), ('Alice', 'trip'), ('alice', None), ('alice', 'trip planning')):
            with self.subTest(user=user, task=task), self.assertRaises(MemoryInputError):
                Scope(user, task)
        with self.assertRaises(MemoryInputError):
            store.recall(ALICE, 'hotel', limit=0)
        self.assertEqual(store.count(ALICE), 0)


if __name__ == '__main__':
    unittest.main()
