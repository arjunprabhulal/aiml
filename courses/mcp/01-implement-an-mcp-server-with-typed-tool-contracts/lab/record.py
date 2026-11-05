"""Save the tools/list result and four tools/call exchanges as JSON. Run: python record.py"""
import asyncio
import importlib
import json
from pathlib import Path

from mcp import Client, types
from mcp.shared.exceptions import MCPError

import tasks_server

CALLS = {
    "add_task ok": ("add_task", {"title": "Tag v1.2", "priority": "high"}),
    "add_task short title": ("add_task", {"title": "v2"}),
    "complete_task T-9": ("complete_task", {"task_id": "T-9"}),
}


def wire(model) -> dict:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"meta", "ttl_ms", "cache_scope", "result_type"})


async def collect() -> dict:
    """Run against a fresh copy of the server's in-memory task list."""
    server = importlib.reload(tasks_server).server
    async with Client(server) as client:
        recorded = {"tools/list": wire(await client.list_tools())}
        for label, (name, arguments) in CALLS.items():
            recorded[label] = wire(await client.call_tool(name, arguments))
        try:
            await client.session.send_request(types.Request(method="tools/call", params={"arguments": {}}), types.CallToolResult)
        except MCPError as error:
            recorded["tools/call without name"] = {"error": {"code": error.code, "message": error.message}}
    return recorded


if __name__ == "__main__":
    out = Path(__file__).with_name("recorded-calls.json")
    out.write_text(json.dumps(asyncio.run(collect()), indent=2) + "\n", encoding="utf-8")
