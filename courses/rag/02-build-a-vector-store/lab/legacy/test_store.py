"""Offline tests for the persistent vector store. No model server is needed."""
import json
import math
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from load_store import build
from store import StoreError, VectorStore

HERE = Path(__file__).parent
DIGEST = 'test-digest'


def unit(*values: float) -> list[float]:
    n = math.sqrt(sum(v * v for v in values))
    return [v / n for v in values]


def passage(i: int, kind: str = 'foundation', topic: str = 'A', minutes: int = 5) -> dict:
    return {'id': f'p{i}', 'lesson': f'lesson-{i}', 'kind': kind, 'topic': topic, 'minutes': minutes,
            'title': f'Passage {i}', 'text': f'text {i}'}


class StoreTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.path = self.folder / 'store.sqlite'

    def store(self) -> VectorStore:
        store = VectorStore.create(self.path, DIGEST, 2)
        self.addCleanup(store.close)
        return store

    def test_fixture_matches_recorded_result(self):
        output = subprocess.run([sys.executable, 'evaluate.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'evaluation-result.json').read_text()))

    def test_reopened_store_returns_the_same_results(self):
        store = self.store()
        store.add([passage(0), passage(1), passage(2)], [unit(1, 0), unit(1, 1), unit(0, 1)], DIGEST)
        before = store.search(unit(1, 0.2), DIGEST, k=3)
        store.close()
        reopened = VectorStore.open(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.search(unit(1, 0.2), DIGEST, k=3), before)

    def test_vectors_or_query_from_another_model_build_are_refused(self):
        store = self.store()
        with self.assertRaisesRegex(StoreError, 'different model build'):
            store.add([passage(0)], [unit(1, 0)], 'other-digest')
        store.add([passage(0)], [unit(1, 0)], DIGEST)
        with self.assertRaisesRegex(StoreError, 'different model build'):
            store.search(unit(1, 0), 'other-digest')

    def test_batch_with_one_invalid_vector_or_duplicate_id_writes_nothing(self):
        store = self.store()
        bad_vectors = ([unit(1, 0), [3.0, 4.0]], [unit(1, 0), [1.0, 0.0, 0.0]], [unit(1, 0), [math.nan, 1.0]])
        for vectors in bad_vectors:
            with self.subTest(vectors=vectors), self.assertRaises(StoreError):
                store.add([passage(0), passage(1)], vectors, DIGEST)
        with self.assertRaisesRegex(StoreError, 'nothing written'):
            store.add([passage(0), passage(0)], [unit(1, 0), unit(0, 1)], DIGEST)
        self.assertEqual(store.count(), 0)

    def test_unknown_field_operator_or_value_type_is_refused(self):
        store = self.store()
        store.add([passage(0)], [unit(1, 0)], DIGEST)
        for where in ({'author': 'x'}, {'topic': {'like': 'A%'}}, {'minutes': '5'}, {'minutes': True},
                      {'topic': {'gte': 'A'}}, {'topic': {'in': []}}, {'topic': {}}):
            with self.subTest(where=where), self.assertRaises(StoreError):
                store.search(unit(1, 0), DIGEST, where=where)

    def test_filter_values_are_parameters_not_sql(self):
        store = self.store()
        store.add([passage(0), passage(1)], [unit(1, 0), unit(0, 1)], DIGEST)
        self.assertEqual(store.search(unit(1, 0), DIGEST, where={'topic': "x' OR '1'='1"}), [])
        with self.assertRaises(StoreError):
            store.search(unit(1, 0), DIGEST, where={'topic = topic OR 1': 'A'})
        self.assertEqual(store.count(), 2)

    def test_post_filter_returns_fewer_results_than_pre_filter(self):
        store = self.store()
        rows = [passage(i, kind='build' if i >= 4 else 'foundation') for i in range(6)]
        store.add(rows, [unit(1, 0.1 * i) for i in range(6)], DIGEST)
        where = {'kind': 'build'}
        self.assertEqual([h['id'] for h in store.search(unit(1, 0), DIGEST, k=2, where=where)], ['p4', 'p5'])
        self.assertEqual(store.search(unit(1, 0), DIGEST, k=2, where=where, filtering='post'), [])
        wider = store.search(unit(1, 0), DIGEST, k=2, where=where, filtering='post', candidates=6)
        self.assertEqual([h['id'] for h in wider], ['p4', 'p5'])
        for options in ({'filtering': 'post', 'candidates': 1}, {'filtering': 'later'}):
            with self.subTest(options=options), self.assertRaises(StoreError):
                store.search(unit(1, 0), DIGEST, k=2, where=where, **options)

    def test_other_schema_version_or_non_database_file_is_refused(self):
        self.store().close()
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA user_version = 2')
        db.close()
        with self.assertRaisesRegex(StoreError, 'schema version 2'):
            VectorStore.open(self.path)
        junk = self.folder / 'junk.sqlite'
        junk.write_bytes(b'not a database' * 100)
        with self.assertRaises(StoreError):
            VectorStore.open(junk)

    def test_create_over_an_existing_file_is_refused(self):
        self.store().add([passage(0)], [unit(1, 0)], DIGEST)
        with self.assertRaisesRegex(StoreError, 'already exists'):
            VectorStore.create(self.path, DIGEST, 2)
        reopened = VectorStore.open(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.count(), 1)

    def test_failed_load_leaves_no_store_file(self):
        source = self.folder / 'source'
        source.mkdir()
        for name in ('corpus.json', 'index.json', 'vectors.f32', 'lesson-metadata.json'):
            shutil.copy(HERE / name, source / name)
        metadata = json.loads((source / 'lesson-metadata.json').read_text())
        next(iter(metadata['lessons'].values()))['kind'] = 'video'
        (source / 'lesson-metadata.json').write_text(json.dumps(metadata))
        with self.assertRaisesRegex(StoreError, 'invalid metadata'):
            build(self.path, source)
        self.assertFalse(self.path.exists())
        (source / 'corpus.json').write_text((source / 'corpus.json').read_text().replace('token', 'tokens', 1))
        with self.assertRaisesRegex(StoreError, 'embed it again'):
            build(self.path, source)
        self.assertFalse(self.path.exists())

    def test_ties_break_by_insertion_order(self):
        store = self.store()
        same = unit(1, 1)
        store.add([passage(i) for i in range(4)], [unit(0, 1), same, same, same], DIGEST)
        self.assertEqual([h['id'] for h in store.search(same, DIGEST, k=3)], ['p1', 'p2', 'p3'])


if __name__ == '__main__':
    unittest.main()
