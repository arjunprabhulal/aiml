"""Use every tool, resource and prompt of docs_server.py and save what the client received.

Usage: python inspect_server.py [--write primitives-results.json]
The SDK client connects to the server object in the same process; the tests also run it over stdio.
"""
import argparse
import asyncio
import json
from pathlib import Path

from mcp import Client, MCPError

import docs_server


def dump(result):
    """The result as wire JSON, without the server identity block in _meta."""
    data = result.model_dump(by_alias=True, exclude_none=True, mode="json")
    data.pop("_meta", None)
    return data


async def attempt(call):
    try:
        return {"result": dump(await call)}
    except MCPError as error:
        return {"error": {"code": error.error.code, "message": error.error.message}}


async def collect(server=docs_server.server):
    async with Client(server) as client:
        return {
            "tools/list": dump(await client.list_tools()),
            "resources/list": dump(await client.list_resources()),
            "resources/templates/list": dump(await client.list_resource_templates()),
            "prompts/list": dump(await client.list_prompts()),
            "search worker": await attempt(client.call_tool("search_docs", {"query": "worker"})),
            "search empty query": await attempt(client.call_tool("search_docs", {"query": "  "})),
            "read index": await attempt(client.read_resource("docs://index")),
            "read page": await attempt(client.read_resource("docs://pages/retries")),
            "read missing page": await attempt(client.read_resource("docs://pages/scheduling")),
            "read unmatched URI": await attempt(client.read_resource("docs://drafts/retries")),
            "get prompt": await attempt(client.get_prompt("review_page", {"slug": "retries"})),
            "get prompt for a missing page": await attempt(client.get_prompt("review_page", {"slug": "scheduling"})),
            "get prompt without slug": await attempt(client.get_prompt("review_page", {})),
            "get unknown prompt": await attempt(client.get_prompt("rewrite_docs", {})),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=Path, help="save the results to this JSON file")
    results = asyncio.run(collect())
    for name, value in results.items():
        if name.endswith("/list"):
            key = next(k for k in value if isinstance(value[k], list))
            shown = f"{key}: " + ", ".join(item["name"] for item in value[key])
        elif "error" in value:
            shown = f"error {value['error']['code']}: {value['error']['message']}"
        else:
            shown = "isError=true" if value["result"].get("isError") else "ok"
        print(f"{name:30} {shown}")
    if (path := parser.parse_args(argv).write):
        path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
