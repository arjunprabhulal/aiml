"""Create a throwaway cluster, run the lesson's queries and role checks, save the results, remove the cluster.

Usage: python record_results.py [--write query-results.json]
Needs PostgreSQL 17 (see lesson_cluster.py) and the pinned packages.
"""
import argparse
import asyncio
import json
import tempfile
from pathlib import Path

import psycopg
from mcp import Client

import postgres_server
from lesson_cluster import LessonCluster
from readonly_query import QueryRejected, run_readonly_query, visible_columns, write_problems

QUERIES = [
    ("first five pages", "SELECT slug, section, words FROM docs.pages ORDER BY slug", 5),
    ("pages per section", "SELECT section, count(*) AS pages FROM docs.pages GROUP BY section ORDER BY section", 50),
    ("one row of a million", "SELECT n FROM generate_series(1, 1000000) AS n", 1),
    ("insert a page", "INSERT INTO docs.pages VALUES ('page-99', 'e-1', 'guides', 100)", 50),
    ("delete inside WITH", "WITH gone AS (DELETE FROM docs.pages RETURNING slug) SELECT * FROM gone", 50),
    ("function that writes", "SELECT lo_create(0)", 50),
    ("read editor emails", "SELECT email FROM docs.editors", 50),
    ("slow query", "SELECT pg_sleep(2)", 50),
    ("two statements", "SELECT 1; SELECT 2", 50),
    ("turn off read-only for the session", "SELECT set_config('default_transaction_read_only', 'off', false)", 50),
    ("function that writes, next call", "SELECT lo_create(0)", 50),
    ("one 300,000-character value", "SELECT repeat('x', 300000) AS big", 1),
    ("send a notification", "SELECT pg_notify('docs', 'hello')", 50),
    ("too many rows requested", "SELECT slug FROM docs.pages", 1000),
]


def tool_results(dsn):
    results = {}
    for label, sql, max_rows in QUERIES:
        try:
            results[label] = {"sql": sql, "max_rows": max_rows, "result": run_readonly_query(dsn, sql, max_rows)}
        except QueryRejected as rejected:
            results[label] = {"sql": sql, "max_rows": max_rows, "rejected": rejected.reason, "sqlstate": rejected.sqlstate}
    return results


def role_checks(dsn):
    """Bypass the tool's limits on purpose: what does the role itself allow?"""
    checks = {}
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = off")  # a session may change its own default
        checks["read-only default after SET"] = conn.execute("SHOW default_transaction_read_only").fetchone()[0]
        for label, sql in [("insert with read-only off", "INSERT INTO docs.pages VALUES ('page-99', 'e-1', 'guides', 100)"),
                           ("delete with read-only off", "DELETE FROM docs.pages"),
                           ("read editors with read-only off", "SELECT email FROM docs.editors"),
                           ("create a large object with read-only off", "SELECT lo_create(0)")]:
            try:
                conn.execute(sql)
                checks[label] = "allowed"
            except psycopg.Error as error:
                checks[label] = f"{error.sqlstate}: {error.diag.message_primary}"
    return checks


async def mcp_results(dsn):
    async with Client(postgres_server.build_server(dsn)) as client:
        tools = await client.list_tools()
        found = await client.call_tool("run_query", {"sql": "SELECT count(*) AS pages FROM docs.pages"})
        denied = await client.call_tool("run_query", {"sql": "SELECT lo_create(0)"})
        tool = tools.tools[0].model_dump(by_alias=True, exclude_none=True, mode="json")
        return {"tool": tool,
                "count": {"isError": found.is_error, "structuredContent": found.structured_content},
                "write": {"isError": denied.is_error, "text": denied.content[0].text}}


def record():
    with tempfile.TemporaryDirectory() as directory:
        with LessonCluster(Path(directory) / "cluster") as cluster:
            dsn = cluster.reader_dsn
            return {"postgres": cluster.version, "visible_columns": visible_columns(dsn), "write_problems": write_problems(dsn),
                    "queries": tool_results(dsn), "role_checks": role_checks(dsn), "mcp": asyncio.run(mcp_results(dsn))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", type=Path, help="save the results to this JSON file")
    options = parser.parse_args(argv)
    results = record()
    print(f"PostgreSQL {results['postgres']}")
    for label, outcome in results["queries"].items():
        if "rejected" in outcome:
            shown = f"rejected: {outcome['rejected']}" + (f" ({outcome['sqlstate']})" if outcome["sqlstate"] else "")
        else:
            shown = f"{len(outcome['result']['rows'])} rows, truncated={outcome['result']['truncated']}"
        print(f"{label:36} {shown}")
    for label, outcome in results["role_checks"].items():
        print(f"role: {label:30} {outcome}")
    if options.write:
        options.write.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {options.write}")


if __name__ == "__main__":
    main()
