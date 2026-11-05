"""Connect to the tasks server over one transport and make two calls.

Run: python client.py stdio                       (starts serve.py as a subprocess)
     python client.py http://127.0.0.1:8000/mcp   (needs: python serve.py --http)
"""
import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters


def target(arg: str):
    if arg == "stdio":
        return StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("serve.py"))])
    return arg  # a URL string selects Streamable HTTP


async def main(arg: str) -> None:
    async with Client(target(arg)) as client:
        print("server  ", client.server_info.name, client.server_info.version, "protocol", client.protocol_version)
        print("tools   ", [tool.name for tool in (await client.list_tools()).tools])
        added = await client.call_tool("add_task", {"title": "Tag v1.2"})
        listed = await client.call_tool("list_tasks", {"status": "open"})
        print("added   ", added.structured_content["id"], "open count", listed.structured_content["count"])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
