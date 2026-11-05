from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import memory
from memory import Clock, MemoryInputError, MemoryNotFound, MemoryStore, SchemaError, Scope, V1_SCHEMA

HERE = Path(__file__).parent
ALICE = Scope('alice', 'trip-planning')
BOB = Scope('bob', 'onboarding')


class ProvenanceAndDeletionTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = str(Path(folder.name) / 'memory.sqlite3')
        self.clock = Clock()

    def open(self, **options):
        store = MemoryStore(self.path, self.clock, **options)
        self.addCleanup(store.close)
        return store

    def test_fixture_matches_recorded_result(self):
        output = subprocess.run([sys.executable, 'demo.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'memory-result.json').read_text()))

    def test_correction_replaces_the_fact_and_keeps_history(self):
        store = self.open()
        old = store.remember(ALICE, 'user', 'Alice is vegetarian.', 'turn-3')
        new = store.correct(ALICE, old, 'Alice eats fish but no meat.', 'turn-12')
        self.assertEqual([m['id'] for m in store.recall(ALICE, 'Alice vegetarian fish meat', limit=5)], [new])
        versions = store.history(ALICE, old)
        self.assertEqual([(v['id'], v['source'], v['supersedes']) for v in versions],
                         [(old, 'turn-3', None), (new, 'turn-12', old)])
        self.assertEqual(store.history(ALICE, new), versions)

    def test_only_the_newest_version_can_be_corrected(self):
        store = self.open()
        old = store.remember(ALICE, 'user', 'Alice is vegetarian.', 'turn-3')
        store.correct(ALICE, old, 'Alice eats fish.', 'turn-12')
        with self.assertRaisesRegex(MemoryInputError, 'already corrected'):
            store.correct(ALICE, old, 'Alice eats meat.', 'turn-13')

    def test_other_users_memories_look_missing(self):
        store = self.open()
        alice_memory = store.remember(ALICE, 'user', 'Alice is vegetarian.', 'turn-3')
        for action in (lambda: store.correct(BOB, alice_memory, 'Changed.', 'turn-1'),
                       lambda: store.forget(BOB, alice_memory, 'Bob asked.'),
                       lambda: store.history(BOB, alice_memory)):
            with self.assertRaises(MemoryNotFound) as caught:
                action()
            self.assertEqual(str(caught.exception), f'no memory {alice_memory} in this scope')
        with self.assertRaises(MemoryNotFound) as missing:
            store.history(BOB, 999)
        self.assertEqual(str(missing.exception), 'no memory 999 in this scope')
        self.assertEqual(len(store.recall(ALICE, 'vegetarian')), 1)

    def test_memory_expires_at_its_exact_time(self):
        store = self.open()
        store.remember(ALICE, 'task', 'The hotel booking code is 4F7Q.', 'turn-5', ttl_days=7)
        expires = datetime.fromisoformat(store.recall(ALICE, 'hotel booking code')[0]['expires_at'])
        self.clock.moment = expires - timedelta(seconds=1)
        self.assertEqual(len(store.recall(ALICE, 'hotel booking code')), 1)
        self.clock.moment = expires
        self.assertEqual(store.recall(ALICE, 'hotel booking code'), [])

    def test_purge_removes_a_memory_at_its_exact_expiry(self):
        store = self.open()
        store.remember(ALICE, 'task', 'The hotel booking code is 4F7Q.', 'turn-5', ttl_days=7)
        expires = datetime.fromisoformat(store.recall(ALICE, 'hotel booking code')[0]['expires_at'])
        self.clock.moment = expires - timedelta(seconds=1)
        self.assertEqual(store.purge_expired(), 0)
        self.clock.moment = expires
        self.assertEqual(store.purge_expired(), 1)

    def test_purge_removes_a_whole_expired_chain(self):
        store = self.open()
        first = store.remember(ALICE, 'task', 'The booking code is 4F7Q.', 'turn-5', ttl_days=7)
        second = store.correct(ALICE, first, 'The booking code is 9K2M.', 'turn-9', ttl_days=7)
        self.clock.advance(days=8)
        self.assertEqual(store.purge_expired(), 2)
        self.assertEqual(store.recall(ALICE, 'booking code'), [])
        with self.assertRaises(MemoryNotFound):
            store.history(ALICE, first)
        self.assertEqual(store.deletions(ALICE), [{'memory_ids': [first, second], 'reason': 'expired',
                                                    'deleted_at': self.clock.peek()}])

    def test_forget_deletes_every_version_and_records_no_text(self):
        store = self.open()
        old = store.remember(ALICE, 'user', "Alice's passport number is P1234567.", 'turn-6')
        new = store.correct(ALICE, old, "Alice's passport number is P7654321.", 'turn-7')
        self.assertEqual(store.forget(ALICE, new, 'user request'), [old, new])
        self.assertEqual(store.recall(ALICE, 'passport number'), [])
        records = store.deletions(ALICE)
        self.assertEqual(records[0]['memory_ids'], [old, new])
        self.assertNotIn('P1234567', json.dumps(records))
        self.assertEqual(store.deletions(BOB), [])

    def test_forgotten_text_is_overwritten_in_the_file(self):
        # None opens the store with its default, which must be secure_delete on.
        for secure, expected in ((None, False), (False, True)):
            with self.subTest(secure_delete=secure):
                path = Path(self.path).with_name(f'secure-{secure}.sqlite3')
                options = {} if secure is None else {'secure_delete': secure}
                store = MemoryStore(str(path), self.clock, **options)
                memory_id = store.remember(ALICE, 'user', "Alice's passport number is P1234567.", 'turn-6')
                store.remember(ALICE, 'user', 'Alice is vegetarian.', 'turn-3')
                store.forget(ALICE, memory_id, 'user request')
                store.close()
                self.assertEqual(b'P1234567' in path.read_bytes(), expected)

    def test_version_1_file_is_migrated(self):
        db = sqlite3.connect(self.path)
        db.executescript(V1_SCHEMA)
        db.execute("INSERT INTO memories (user_id, task_id, text, source, created_at) "
                   "VALUES ('alice', NULL, 'Alice is vegetarian.', 'turn-3', '2026-10-01T09:00:00+00:00')")
        db.execute('PRAGMA user_version = 1')
        db.commit()
        db.close()
        store = self.open()
        self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertEqual(store.recall(ALICE, 'vegetarian')[0]['source'], 'turn-3')
        new = store.correct(ALICE, 1, 'Alice eats fish.', 'turn-12')
        self.assertEqual(store.history(ALICE, new)[0]['id'], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            with store.db:
                store.db.execute("INSERT INTO memories (user_id, text, source, created_at, supersedes) "
                                 "VALUES ('alice', 'x', 's', 't', 999)")

    def test_failed_migration_leaves_version_1_intact(self):
        db = sqlite3.connect(self.path)
        db.executescript(V1_SCHEMA)
        db.execute("INSERT INTO memories (user_id, task_id, text, source, created_at) "
                   "VALUES ('alice', NULL, 'Alice is vegetarian.', 'turn-3', '2026-10-01T09:00:00+00:00')")
        db.execute('PRAGMA user_version = 1')
        db.commit()
        db.close()
        original = memory.V2_FINISH
        memory.V2_FINISH = [*original[:1], 'THIS IS NOT SQL', *original[1:]]
        try:
            with self.assertRaises(sqlite3.OperationalError):
                MemoryStore(self.path, self.clock)
        finally:
            memory.V2_FINISH = original
        db = sqlite3.connect(self.path)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertEqual([row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")],
                         ['memories'])
        self.assertEqual(db.execute('SELECT text FROM memories').fetchall(), [('Alice is vegetarian.',)])
        db.close()

    def test_unknown_or_foreign_files_are_refused(self):
        db = sqlite3.connect(self.path)
        db.execute('CREATE TABLE notes (body TEXT)')
        db.execute('PRAGMA user_version = 1')
        db.commit()
        db.close()
        with self.assertRaises(SchemaError):
            MemoryStore(self.path, self.clock)
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA user_version = 3')
        db.close()
        with self.assertRaisesRegex(SchemaError, 'version 3'):
            MemoryStore(self.path, self.clock)

    def test_invalid_input_is_rejected_before_writing(self):
        store = self.open()
        memory_id = store.remember(ALICE, 'user', 'Alice is vegetarian.', 'turn-3')
        for action in (lambda: store.remember(ALICE, 'user', 'x', 'turn-1', ttl_days=0),
                       lambda: store.remember(ALICE, 'user', 'x', 'turn-1', ttl_days=True),
                       lambda: store.remember(ALICE, 'global', 'x', 'turn-1'),
                       lambda: store.correct(ALICE, memory_id, ' ', 'turn-2'),
                       lambda: store.forget(ALICE, memory_id, ' ')):
            with self.assertRaises(MemoryInputError):
                action()
        self.assertEqual(len(store.history(ALICE, memory_id)), 1)
        self.assertEqual(store.deletions(ALICE), [])


if __name__ == '__main__':
    unittest.main()
