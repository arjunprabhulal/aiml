"""Tests for the read-only PostgreSQL MCP tool. Each run creates and removes its own PostgreSQL 17 cluster.

    python -m unittest -v test_postgres_readonly.py
"""
import asyncio
import json
import resource
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import psycopg
from mcp import Client

import postgres_server
import record_results
from lesson_cluster import LessonCluster
import lesson_cluster
from readonly_query import QueryRejected, check_reader, run_readonly_query, visible_columns, write_problems

HERE = Path(__file__).resolve().parent
CLUSTER = None


def setUpModule():
    global CLUSTER, WORKDIR
    WORKDIR = tempfile.TemporaryDirectory()
    CLUSTER = LessonCluster(Path(WORKDIR.name) / "cluster").create()


def tearDownModule():
    CLUSTER.destroy()
    WORKDIR.cleanup()


def admin(sql):
    with psycopg.connect(CLUSTER.admin_dsn(), autocommit=True) as conn:
        conn.execute(sql)


def peak_rss_mb():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 2**20 if sys.platform == "darwin" else peak / 2**10  # bytes on macOS, KiB on Linux


def rejected(sql, max_rows=50):
    try:
        run_readonly_query(CLUSTER.reader_dsn, sql, max_rows)
    except QueryRejected as error:
        return error.sqlstate, error.reason
    raise AssertionError(f"query was not rejected: {sql}")


class AllowedQueries(unittest.TestCase):
    def test_select_returns_columns_and_rows(self):
        result = run_readonly_query(CLUSTER.reader_dsn, "SELECT slug, section FROM docs.pages ORDER BY slug", 2)
        self.assertEqual(result, {"columns": ["slug", "section"], "rows": [["page-01", "reference"], ["page-02", "changelog"]], "truncated": True})

    def test_row_limit_reports_truncation_only_when_rows_were_dropped(self):
        self.assertFalse(run_readonly_query(CLUSTER.reader_dsn, "SELECT slug FROM docs.pages", 30)["truncated"])
        self.assertTrue(run_readonly_query(CLUSTER.reader_dsn, "SELECT slug FROM docs.pages", 29)["truncated"])

    def test_schema_shows_only_granted_table(self):
        tables = {column["table"] for column in visible_columns(CLUSTER.reader_dsn)}
        self.assertEqual(tables, {"docs.pages"})


class Limits(unittest.TestCase):
    def test_insert_is_rejected_by_the_cursor(self):
        self.assertEqual(rejected("INSERT INTO docs.pages VALUES ('page-99', 'e-1', 'guides', 100)")[0], "42601")

    def test_data_modifying_with_is_rejected(self):
        self.assertEqual(rejected("WITH gone AS (DELETE FROM docs.pages RETURNING slug) SELECT * FROM gone")[0], "0A000")

    def test_write_is_rejected_by_read_only_transaction(self):
        self.assertEqual(rejected("SELECT lo_create(0)")[0], "25006")

    def test_unprivileged_table_is_rejected(self):
        self.assertEqual(rejected("SELECT email FROM docs.editors")[0], "42501")

    def test_slow_query_is_cancelled_by_statement_timeout(self):
        self.assertEqual(rejected("SELECT pg_sleep(2)")[0], "57014")

    def test_multiple_statements_are_rejected(self):
        self.assertEqual(rejected("SELECT 1; SELECT 2")[0], "42601")

    def test_session_setting_does_not_carry_into_the_next_call(self):
        run_readonly_query(CLUSTER.reader_dsn, "SELECT set_config('default_transaction_read_only', 'off', false)")
        self.assertEqual(rejected("SELECT lo_create(0)")[0], "25006")

    def test_bad_max_rows_and_empty_sql_are_rejected_before_the_database(self):
        for max_rows in (0, 201, True, "5"):
            with self.subTest(max_rows=max_rows):
                self.assertEqual(rejected("SELECT 1", max_rows), (None, "max_rows must be an integer from 1 to 200"))
        self.assertEqual(rejected("   "), (None, "the query is empty"))

    def test_large_result_stays_on_the_server(self):
        before = peak_rss_mb()
        result = run_readonly_query(CLUSTER.reader_dsn, "SELECT n FROM generate_series(1, 3000000) AS n", 1)
        self.assertEqual((result["rows"], result["truncated"]), ([[1]], True))
        self.assertLess(peak_rss_mb() - before, 64)  # buffering 3,000,000 rows in the client would add hundreds of MB

    def test_result_byte_budget_rejects_large_values_and_many_wide_rows(self):
        reason = "the result is larger than 200000 bytes; select fewer or shorter values"
        self.assertEqual(rejected("SELECT repeat('x', 300000)", 1), (None, reason))
        self.assertEqual(rejected("SELECT repeat('x', 2000) FROM generate_series(1, 200)", 200), (None, reason))
        self.assertEqual(len(run_readonly_query(CLUSTER.reader_dsn, "SELECT repeat('x', 900) FROM generate_series(1, 200)", 200)["rows"]), 200)

    def test_notification_is_not_a_write_and_is_allowed(self):
        # A gap to know about: pg_notify signals listening sessions even in a read-only transaction.
        self.assertEqual(run_readonly_query(CLUSTER.reader_dsn, "SELECT pg_notify('docs', 'hello')")["rows"], [[""]])

    def test_transaction_limits_hold_without_role_defaults(self):
        admin("ALTER ROLE mcp_reader IN DATABASE docs_lesson RESET ALL")
        try:
            self.assertEqual(rejected("SELECT lo_create(0)")[0], "25006")  # needs SET TRANSACTION READ ONLY
            self.assertEqual(rejected("SELECT pg_sleep(2)")[0], "57014")   # needs the per-transaction timeout
        finally:
            admin("ALTER ROLE mcp_reader IN DATABASE docs_lesson SET default_transaction_read_only = on")
            admin("ALTER ROLE mcp_reader IN DATABASE docs_lesson SET statement_timeout = '500ms'")


class RolePrivileges(unittest.TestCase):
    def test_role_cannot_write_even_with_read_only_turned_off(self):
        with psycopg.connect(CLUSTER.reader_dsn, autocommit=True) as conn:
            conn.execute("SET default_transaction_read_only = off")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("DELETE FROM docs.pages")

    def test_table_grants_do_not_cover_large_objects(self):
        # A gap the read-only transaction closes: with read-only off, the reader can create a large object.
        with psycopg.connect(CLUSTER.reader_dsn) as conn:
            conn.execute("SET TRANSACTION READ WRITE")  # the first statement of this transaction
            oid = conn.execute("SELECT lo_create(0)").fetchone()[0]
            conn.rollback()
        self.assertIsInstance(oid, int)

    def test_server_refuses_a_role_that_can_write(self):
        with self.assertRaises(SystemExit):
            check_reader(CLUSTER.admin_dsn())
        self.assertEqual(write_problems(CLUSTER.reader_dsn), [])
        check_reader(CLUSTER.reader_dsn)  # the read-only role passes

    def test_check_finds_write_grants_the_role_could_inherit(self):
        grants = {
            "pg_write_all_data": ("GRANT pg_write_all_data TO mcp_reader", "REVOKE pg_write_all_data FROM mcp_reader",
                                  "is a member of pg_write_all_data"),
            "owner membership": ("GRANT docs_owner TO mcp_reader", "REVOKE docs_owner FROM mcp_reader",
                                 "can change rows or columns of a table"),
            "column UPDATE": ("GRANT UPDATE (section) ON docs.pages TO mcp_reader", "REVOKE UPDATE (section) ON docs.pages FROM mcp_reader",
                              "can change rows or columns of a table"),
            "membership without inherit": ("GRANT docs_owner TO mcp_reader WITH INHERIT FALSE", "REVOKE docs_owner FROM mcp_reader",
                                           "is a member of another role, which SET ROLE could switch to"),
        }
        for label, (grant, revoke, problem) in grants.items():
            with self.subTest(label):
                admin(grant)
                try:
                    self.assertIn(problem, write_problems(CLUSTER.reader_dsn))
                    with self.assertRaises(SystemExit):
                        check_reader(CLUSTER.reader_dsn)
                finally:
                    admin(revoke)
        self.assertEqual(write_problems(CLUSTER.reader_dsn), [])

    def test_reader_cannot_connect_to_other_databases(self):
        with self.assertRaises(psycopg.OperationalError):
            psycopg.connect(CLUSTER.reader_dsn.replace("dbname=docs_lesson", "dbname=postgres"), connect_timeout=2)

    def test_destroy_refuses_directories_that_are_not_lesson_clusters(self):
        with tempfile.TemporaryDirectory() as directory:
            keep = Path(directory) / "notes.txt"
            keep.write_text("not a cluster")
            with self.assertRaises(SystemExit):
                LessonCluster(directory).destroy()
            self.assertTrue(keep.exists())
        for unsafe in ("", "   ", ".", str(Path.home())):
            with self.subTest(path=unsafe), self.assertRaises(SystemExit):
                LessonCluster(unsafe)

    def test_failed_create_leaves_no_running_server(self):
        with tempfile.TemporaryDirectory() as directory:
            cluster = LessonCluster(Path(directory) / "broken")
            with mock.patch.object(LessonCluster, "seed", side_effect=RuntimeError("seed failed")):
                with self.assertRaises(RuntimeError):
                    cluster.create()
            self.assertFalse((Path(directory) / "broken").exists())
            with socket.socket() as probe:
                self.assertNotEqual(probe.connect_ex(("127.0.0.1", cluster.port)), 0)

    def test_destroy_stops_the_cluster_and_removes_its_files(self):
        with tempfile.TemporaryDirectory() as directory:
            cluster = LessonCluster(Path(directory) / "second").create()
            dsn = cluster.reader_dsn
            cluster.destroy()
            self.assertFalse((Path(directory) / "second").exists())
            with self.assertRaises(psycopg.OperationalError):
                psycopg.connect(dsn, connect_timeout=2)


class McpLayer(unittest.TestCase):
    def call(self, arguments):
        async def run():
            async with Client(postgres_server.build_server(CLUSTER.reader_dsn)) as client:
                return await client.call_tool("run_query", arguments)
        return asyncio.run(run())

    def test_denied_query_is_a_tool_error_with_sqlstate(self):
        result = self.call({"sql": "SELECT lo_create(0)"})
        self.assertTrue(result.is_error)
        self.assertIn("Query rejected: the transaction is read-only (SQLSTATE 25006).", result.content[0].text)

    def test_schema_bounds_max_rows_and_extra_properties_are_ignored(self):
        self.assertTrue(self.call({"sql": "SELECT 1", "max_rows": "5"}).is_error)   # strict integer
        self.assertTrue(self.call({"sql": "SELECT 1", "max_rows": 201}).is_error)   # maximum 200
        ignored = self.call({"sql": "SELECT 1", "extra": "value"})                 # mcp 2.3.0 drops unknown keys
        self.assertEqual((ignored.is_error, ignored.structured_content["rows"]), (False, [[1]]))


class RecordedResults(unittest.TestCase):
    def test_saved_results_match_a_fresh_run(self):
        self.assertEqual(json.loads((HERE / "query-results.json").read_text()), record_results.record())


if __name__ == "__main__":
    unittest.main()
