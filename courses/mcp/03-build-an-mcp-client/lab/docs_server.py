"""The docs server the traced client talks to. Run with `python docs_server.py`.

If MCP_SPANS_FILE is set, the server writes its OpenTelemetry spans there. mcp 2.3.0
creates a server span for every request and continues the trace the client sends in _meta.
"""
import os
import time
from typing import TypedDict

from opentelemetry import trace

if os.environ.get("MCP_SPANS_FILE"):
    from span_export import configure
    configure(os.environ["MCP_SPANS_FILE"])

from mcp.server import MCPServer
from mcp.server.caching import CacheHint
from mcp.server.mcpserver.exceptions import ToolError

PAGES = {"quickstart": "Start a worker with taskq worker emails.",
         "retries": "A failed job is retried 3 times with exponential backoff."}
server = MCPServer("docs", version="1.0.0", instructions="Search the taskq docs.",
                   cache_hints={"tools/list": CacheHint(ttl_ms=60_000, scope="public")})
tracer = trace.get_tracer("docs")


class SearchHit(TypedDict):
    slug: str
    text: str


@server.tool()
def search_docs(query: str) -> list[SearchHit]:
    """Return the docs pages that contain the query."""
    with tracer.start_as_current_span("docs.search") as span:
        if not query.strip():
            raise ToolError("The query is empty.")
        hits = [{"slug": slug, "text": text} for slug, text in PAGES.items() if query.lower() in text.lower()]
        span.set_attribute("docs.hits", len(hits))
        return hits


@server.tool()
def rebuild_index(seconds: float) -> str:
    """Rebuild the search index; takes `seconds` seconds."""
    time.sleep(seconds)
    return "index rebuilt"


if __name__ == "__main__":
    server.run()
