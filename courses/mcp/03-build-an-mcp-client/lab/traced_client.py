"""An MCP client that keeps what discovery tells it, checks calls before sending and traces each one.

Usage: python traced_client.py [--write-log execution-log.json] [--write-trace trace-tree.json]
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import jsonschema
from opentelemetry import trace

from mcp import Client, MCPError, StdioServerParameters
from mcp.types import REQUEST_TIMEOUT
from span_export import configure, span_tree

HERE = Path(__file__).resolve().parent
tracer = trace.get_tracer("traced-client")


class TracedClient:
    """Wraps an SDK Client: remembers discovery, lists tools only if offered, and classifies every call."""

    def __init__(self, client):
        self.client, self.tools, self.log = client, {}, []

    def discovery(self):
        caps, info = self.client.server_capabilities, self.client.server_info
        return {"protocol_version": self.client.protocol_version, "server": f"{info.name} {info.version}",
                "capabilities": [name for name in ("tools", "resources", "prompts") if getattr(caps, name) is not None]}

    async def load_tools(self):
        if self.client.server_capabilities.tools is None:
            self.log.append({"request": "tools/list", "outcome": "skipped", "detail": "server does not offer tools"})
            return
        self.tools = {tool.name: tool for tool in (await self.client.list_tools()).tools}
        self.log.append({"request": "tools/list", "outcome": "result", "detail": sorted(self.tools)})

    async def call(self, name, arguments, timeout=5.0):
        with tracer.start_as_current_span(f"app call {name}") as span:
            outcome, detail = await self._call(name, arguments, timeout)
            span.set_attribute("app.outcome", outcome)
        self.log.append({"request": f"tools/call {name}", "arguments": arguments, "outcome": outcome, "detail": detail})

    async def _call(self, name, arguments, timeout):
        tool = self.tools.get(name)
        if tool is None:
            return "refused_locally", "tool is not in the server's tools/list"
        problem = jsonschema.exceptions.best_match(jsonschema.Draft202012Validator(tool.input_schema).iter_errors(arguments))
        if problem:
            return "refused_locally", f"arguments do not match inputSchema: {problem.message}"
        try:
            result = await self.client.call_tool(name, arguments, read_timeout_seconds=timeout)
        except MCPError as error:
            return ("timeout" if error.error.code == REQUEST_TIMEOUT else "protocol_error"), error.error.message
        except RuntimeError as error:  # mcp 2.3.0 checks structuredContent against outputSchema and raises this
            return "invalid_output", str(getattr(error.__cause__, "message", error))
        if result.is_error:
            return "tool_error", result.content[0].text
        return "result", result.structured_content


def server(script, **env):
    return StdioServerParameters(command=sys.executable, args=[str(HERE / script)], env={**os.environ, **env})


async def docs_session(server_spans):
    async with Client(server("docs_server.py", MCP_SPANS_FILE=str(server_spans))) as client:
        with tracer.start_as_current_span("answer docs question"):
            app = TracedClient(client)
            discovery = app.discovery()
            await app.load_tools()
            await app.load_tools()  # served from the SDK's cache: the listing has ttlMs 60000
            await app.call("search_docs", {"query": "worker"})
            await app.call("search_docs", {"query": 42})
            await app.call("search_docs", {"query": " "})
            await app.call("rebuild_index", {"seconds": 1.0}, timeout=0.2)
            await app.call("search_docs", {"query": "retried"})
            await app.call("delete_page", {"slug": "retries"})
    return {"discovery": discovery, "log": app.log}


async def broken_session():
    async with Client(server("broken_server.py")) as client:
        app = TracedClient(client)
        discovery = app.discovery()
        await app.load_tools()
        await app.call("search_docs", {"query": "retries"})
    return {"discovery": discovery, "log": app.log}


def run(directory):
    """Run both sessions with span files in `directory`; return the execution log and the joined trace."""
    client_spans, server_spans = Path(directory) / "client-spans.jsonl", Path(directory) / "server-spans.jsonl"
    configure(client_spans)
    docs = asyncio.run(docs_session(server_spans))
    tree = span_tree(client_spans, server_spans)
    return {"docs": docs, "broken": asyncio.run(broken_session())}, tree


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-log", type=Path)
    parser.add_argument("--write-trace", type=Path)
    options = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as directory:
        log, tree = run(directory)
    for data in log.values():
        print(f"== {data['discovery']['server']} offers {', '.join(data['discovery']['capabilities'])}")
        for entry in data["log"]:
            print(f"  {entry['request']:26} {entry['outcome']:16} {json.dumps(entry['detail'])[:64]}")
    print(f"trace: {tree['spans']} spans in {tree['traces']} trace(s)")
    for path, data in ((options.write_log, log), (options.write_trace, tree)):
        if path:
            path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"wrote {path}")


if __name__ == "__main__":
    main()
