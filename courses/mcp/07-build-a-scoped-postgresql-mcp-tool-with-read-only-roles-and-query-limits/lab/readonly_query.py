"""Run one model-written SQL query under read-only limits.

run_readonly_query() opens a new connection as the read-only role, starts a
READ ONLY transaction, sets a statement timeout for that transaction, and runs
the query through a named server-side cursor. PostgreSQL keeps the result on
the server; the tool fetches at most max_rows + 1 rows. The role's privileges
are the real boundary; these limits narrow what a query can do within them.
"""
import datetime
import decimal
import json

import psycopg

MAX_ROWS_LIMIT = 200
DEFAULT_MAX_ROWS = 50
TIMEOUT_MS = 500
MAX_RESULT_BYTES = 200_000  # JSON size of the returned rows

# SQLSTATE codes this tool expects, with the reason it reports.
REASONS = {
    "25006": "the transaction is read-only",
    "42501": "the role lacks the privilege",
    "57014": f"the query ran longer than {TIMEOUT_MS} ms",
    "42601": "only one SELECT or VALUES query is allowed",
    "0A000": "the query uses a feature a cursor does not allow, such as a data-modifying WITH",
    "42P01": "the table does not exist or is not visible",
    "42703": "a column does not exist",
}

WRITE_CHECK = """
SELECT r.rolsuper, r.rolcreaterole, r.rolcreatedb,
       pg_has_role(current_user, 'pg_write_all_data', 'USAGE'),
       EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%'
                 AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                 AND (has_table_privilege(current_user, c.oid, 'INSERT, UPDATE, DELETE, TRUNCATE')
                      OR has_any_column_privilege(current_user, c.oid, 'INSERT, UPDATE'))),
       EXISTS (SELECT 1 FROM pg_namespace n
               WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%'
                 AND has_schema_privilege(current_user, n.oid, 'CREATE')),
       has_database_privilege(current_user, current_database(), 'CREATE, TEMP'),
       EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member = r.oid)
FROM pg_roles r WHERE r.rolname = current_user
"""
WRITE_PROBLEMS = ["is a superuser", "can create roles", "can create databases", "is a member of pg_write_all_data",
                  "can change rows or columns of a table", "can create objects in a schema",
                  "can create schemas or temporary tables in the database",
                  "is a member of another role, which SET ROLE could switch to"]


class QueryRejected(Exception):
    """The query did not run, or PostgreSQL stopped it."""

    def __init__(self, reason, sqlstate=None):
        super().__init__(reason)
        self.reason, self.sqlstate = reason, sqlstate


def to_json_value(value):
    """Turn a database value into something json.dumps can write."""
    if isinstance(value, (datetime.date, datetime.datetime, decimal.Decimal)):
        return str(value)
    return value


def run_readonly_query(reader_dsn, sql, max_rows=DEFAULT_MAX_ROWS):
    if not isinstance(sql, str) or not sql.strip():
        raise QueryRejected("the query is empty")
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= MAX_ROWS_LIMIT:
        raise QueryRejected(f"max_rows must be an integer from 1 to {MAX_ROWS_LIMIT}")
    try:
        # A new connection per call: a SET or set_config() from an earlier query cannot carry over.
        with psycopg.connect(reader_dsn, connect_timeout=5) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute("SELECT set_config('statement_timeout', %s, true)", (f"{TIMEOUT_MS}ms",))
                # A named cursor is a server-side DECLARE ... CURSOR FOR <query>: PostgreSQL accepts one
                # SELECT or VALUES query, and keeps the result on the server until it is fetched.
                with conn.cursor(name="run_query") as cursor:
                    cursor.execute(sql)
                    rows = cursor.fetchmany(max_rows + 1)
                    columns = [column.name for column in cursor.description]
    except psycopg.Error as error:
        state = error.sqlstate
        raise QueryRejected(REASONS.get(state, "PostgreSQL rejected the query"), state) from None
    result_rows, size = [], 0
    for row in rows[:max_rows]:
        values = [to_json_value(value) for value in row]
        size += len(json.dumps(values, default=str))
        if size > MAX_RESULT_BYTES:
            # The rows were already fetched, so this bounds what the model receives, not what PostgreSQL sent.
            raise QueryRejected(f"the result is larger than {MAX_RESULT_BYTES} bytes; select fewer or shorter values")
        result_rows.append(values)
    return {"columns": columns, "rows": result_rows, "truncated": len(rows) > max_rows}


def visible_columns(reader_dsn):
    """Columns the reader can see. information_schema shows only objects the role has privileges on."""
    with psycopg.connect(reader_dsn, connect_timeout=5) as conn:
        rows = conn.execute(
            "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
            "ORDER BY table_schema, table_name, ordinal_position").fetchall()
    return [{"table": f"{schema}.{table}", "column": column, "type": kind} for schema, table, column, kind in rows]


def write_problems(reader_dsn):
    """Ways the connected role could change data or objects in this database; an empty list means none found."""
    with psycopg.connect(reader_dsn, connect_timeout=5) as conn:
        flags = conn.execute(WRITE_CHECK).fetchone()
    return [problem for problem, flag in zip(WRITE_PROBLEMS, flags) if flag]


def check_reader(reader_dsn):
    """Refuse to serve with a role that could write."""
    problems = write_problems(reader_dsn)
    if problems:
        raise SystemExit("refusing to serve: the database role " + "; ".join(problems))
