"""Tests for the comparison. All but the last run offline with the standard library.

The last test needs PostgreSQL with pgvector and pg8000; it runs only when
PGVECTOR_URL is set, and uses its own schema, which it drops afterwards.
"""
from array import array
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.parse import urlparse
from pgvector_store import PgvectorError, PgvectorStore, parse_vector, vector_text
from search import VectorIndex

HERE = Path(__file__).parent


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rows = conn, []

    def execute(self, sql, params=None):
        self.conn.log.append((' '.join(sql.split()), params))
        self.rows = self.conn.respond(sql)

    def executemany(self, sql, rows):
        self.conn.log.append((' '.join(sql.split()), list(rows)))

    def fetchall(self):
        return self.rows


class FakeConnection:
    """Records every statement; answers the few queries the store reads."""
    def __init__(self, schema_exists=False, digest='digest'):
        self.log, self.schema_exists, self.digest = [], schema_exists, digest

    def respond(self, sql):
        if 'information_schema.schemata' in sql:
            return [(1,)] if self.schema_exists else []
        if '.meta' in sql and sql.startswith('SELECT'):
            return [('model_digest', self.digest), ('dimensions', '2')]
        if sql.startswith('SELECT id'):
            return [('p0', 'lesson-0', 0.9)]
        return []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.log.append(('COMMIT', None))

    def rollback(self):
        self.log.append(('ROLLBACK', None))


class CompareTest(unittest.TestCase):
    def test_fixture_matches_recorded_result(self):
        output = subprocess.run([sys.executable, 'compare.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'evaluation-result.json').read_text()))

    def test_vectors_round_trip_through_text_exactly(self):
        base = VectorIndex()
        for vector in base.vectors[:25]:
            self.assertEqual(array('f', parse_vector(vector_text(vector))).tobytes(), array('f', vector).tobytes())
        for bad in ([], [1.0, float('nan')], [float('inf')]):
            with self.subTest(bad=bad), self.assertRaises(PgvectorError):
                vector_text(bad)

    def test_filter_values_and_settings_never_become_sql_text(self):
        conn = FakeConnection()
        store = PgvectorStore(conn, 'compare')
        store.search([1.0, 0.0], 'digest', k=5, where={'topic': "x' OR '1'='1"},
                     settings={'hnsw.ef_search': 40, 'hnsw.iterative_scan': 'strict_order'})
        sql, params = conn.log[-2]
        self.assertIn('WHERE topic = %s ORDER BY', sql)
        self.assertNotIn("OR '1'='1", sql)
        self.assertEqual(params[1], "x' OR '1'='1")
        refused = [{'where': {'author': 'x'}}, {'where': {'kind': 3}},
                   {'settings': {'work_mem': '1GB'}}, {'settings': {'ivfflat.probes': 0}},
                   {'settings': {'ivfflat.probes': True}}, {'settings': {'hnsw.ef_search': '40; DROP TABLE x'}},
                   {'settings': {'hnsw.iterative_scan': 'maybe'}}]
        for options in refused:
            with self.subTest(options=options), self.assertRaises(PgvectorError):
                store.search([1.0, 0.0], 'digest', **options)

    def test_settings_last_only_for_one_query(self):
        conn = FakeConnection()
        PgvectorStore(conn, 'compare').search([1.0, 0.0], 'digest', settings={'ivfflat.probes': 4})
        statements = [sql for sql, _ in conn.log[-3:]]
        self.assertEqual(statements[0], 'SET LOCAL ivfflat.probes = 4')
        self.assertTrue(statements[1].startswith('SELECT id'))
        self.assertEqual(statements[2], 'COMMIT')

    def test_query_orders_by_distance_only(self):
        sql, _ = PgvectorStore(FakeConnection(), 'compare').query_sql({'kind': 'build'})
        self.assertTrue(sql.endswith('ORDER BY embedding <=> %s::vector LIMIT %s'))

    def test_query_or_vectors_from_another_model_build_are_refused(self):
        store = PgvectorStore(FakeConnection(digest='stored-digest'), 'compare')
        with self.assertRaisesRegex(PgvectorError, 'different model build'):
            store.search([1.0, 0.0], 'other-digest')
        with self.assertRaisesRegex(PgvectorError, 'different model build'):
            store.add([{'id': 'p0', 'lesson': 'l', 'kind': 'build', 'topic': 't'}], [[1.0, 0.0]], 'other-digest')

    def test_schema_names_and_index_options_are_checked(self):
        conn = FakeConnection()
        for schema in ('public; DROP TABLE x', 'Compare', ''):
            with self.subTest(schema=schema), self.assertRaises(PgvectorError):
                PgvectorStore(conn, schema)
        store = PgvectorStore(conn, 'compare')
        for method, options in (('flat', {}), ('ivfflat', {'lists': 0}), ('ivfflat', {'lists': '16'}),
                                ('hnsw', {'lists': 16}), ('hnsw', {'m': True})):
            with self.subTest(method=method, options=options), self.assertRaises(PgvectorError):
                store.create_index(method, **options)

    def test_create_refuses_an_existing_schema(self):
        conn = FakeConnection(schema_exists=True)
        with self.assertRaisesRegex(PgvectorError, 'already exists'):
            PgvectorStore.create(conn, 'compare', 'digest', 2)
        self.assertEqual(conn.log[-1], ('ROLLBACK', None))
        self.assertFalse(any(sql.startswith(('CREATE', 'DROP')) for sql, _ in conn.log))

    @unittest.skipUnless(os.environ.get('PGVECTOR_URL'), 'set PGVECTOR_URL to run against PostgreSQL with pgvector')
    def test_live_store_matches_exact_search(self):
        import pg8000.dbapi
        url = urlparse(os.environ['PGVECTOR_URL'])
        conn = pg8000.dbapi.connect(user=url.username, password=url.password, host=url.hostname,
                                    port=url.port or 5432, database=url.path.lstrip('/'))
        self.addCleanup(conn.close)
        schema = 'aiml_vector_test'
        cursor = conn.cursor()
        cursor.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE')
        conn.commit()
        self.addCleanup(lambda: (conn.cursor().execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE'), conn.commit()))
        base = VectorIndex()
        digest = base.record['model']['ollama_digest']
        lessons = json.loads((HERE / 'lesson-metadata.json').read_text())['lessons']
        store = PgvectorStore.create(conn, schema, digest, base.dimensions)
        store.add([{**p, **lessons[p['lesson']]} for p in base.passages], base.vectors, digest)
        for i in (0, 100, 346):
            exact = [h['id'] for h in base.search(base.vectors[i], digest, k=5)]
            self.assertEqual([h['id'] for h in store.search(base.vectors[i], digest, k=5)], exact)
        store.create_index('ivfflat', lists=4)
        probe_all = {'ivfflat.probes': 4, 'enable_seqscan': 'off'}
        exact = {h['id'] for h in base.search(base.vectors[7], digest, k=5)}
        self.assertEqual({h['id'] for h in store.search(base.vectors[7], digest, k=5, settings=probe_all)}, exact)
        store.create_index('hnsw')
        store.drop_metadata_indexes()
        hits = store.search(base.vectors[7], digest, k=5, where={'kind': 'build'},
                            settings={'hnsw.iterative_scan': 'strict_order', 'enable_seqscan': 'off'})
        self.assertEqual(len(hits), 5)
        self.assertTrue(all(lessons[h['lesson']]['kind'] == 'build' for h in hits))


if __name__ == '__main__':
    unittest.main()
