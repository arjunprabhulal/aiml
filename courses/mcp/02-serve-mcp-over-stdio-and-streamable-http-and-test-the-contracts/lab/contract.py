"""Write the server's tools/list result to tools-contract.json. Run: python contract.py

Review the diff of this file like code: a changed schema breaks every client that relies on it.
"""
import asyncio
import json
from pathlib import Path

from mcp import Client

from tasks_server import server

CONTRACT = Path(__file__).with_name("tools-contract.json")


async def published_tools() -> list[dict]:
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    return [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools]


if __name__ == "__main__":
    CONTRACT.write_text(json.dumps(asyncio.run(published_tools()), indent=2) + "\n", encoding="utf-8")
