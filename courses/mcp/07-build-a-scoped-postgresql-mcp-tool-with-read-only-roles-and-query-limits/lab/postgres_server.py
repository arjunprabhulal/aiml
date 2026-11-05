"""An MCP server that lets a model run read-only SQL against the lesson database.

Usage: DOCS_READER_DSN="host=localhost port=54329 ..." python postgres_server.py
The DSN must name the read-only role created by lesson_cluster.py. At start-up the
server refuses a role with any write capability its check knows about: superuser,
role or database creation, pg_write_all_data, table or column write privileges, or
CREATE or TEMP privileges. Built with the official MCP
Python SDK (mcp 2.3.0) and psycopg 3.
"""
import json
import os
import sys
from typing import Annotated, Any, TypedDict

from pydantic import Field

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from readonly_query import DEFAULT_MAX_ROWS, MAX_ROWS_LIMIT, QueryRejected, check_reader, run_readonly_query, visible_columns


class QueryResult(TypedDict):
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool


def build_server(reader_dsn):
    server = MCPServer("docs-sql", version="1.0.0",
                       instructions="Read-only SQL over schema docs. Read postgres://docs/schema for the visible columns.")

    @server.tool(title="Run a read-only SQL query", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def run_query(sql: Annotated[str, Field(min_length=1, max_length=10_000)],
                  max_rows: Annotated[int, Field(ge=1, le=MAX_ROWS_LIMIT, strict=True)] = DEFAULT_MAX_ROWS) -> QueryResult:
        """Run one SELECT or VALUES query on the docs database. Returns at most max_rows rows (200 at most) and 200,000 bytes; each query stops after 500 ms."""
        try:
            return run_readonly_query(reader_dsn, sql, max_rows)
        except QueryRejected as rejected:
            code = f" (SQLSTATE {rejected.sqlstate})" if rejected.sqlstate else ""
            raise ToolError(f"Query rejected: {rejected.reason}{code}.") from None

    @server.resource("postgres://docs/schema", title="Visible tables and columns", mime_type="application/json")
    def schema() -> str:
        """The tables and columns the read-only role can see."""
        return json.dumps(visible_columns(reader_dsn), indent=2)

    return server


if __name__ == "__main__":
    dsn = os.environ.get("DOCS_READER_DSN")
    if not dsn:
        sys.exit("set DOCS_READER_DSN to the read-only role's connection string")
    check_reader(dsn)
    build_server(dsn).run()
