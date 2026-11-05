"""Connect to the tasks server in-process, list its tools and make four calls. Run: python client.py"""
import asyncio

from mcp import Client, types
from mcp.shared.exceptions import MCPError

from tasks_server import server


async def main() -> None:
    async with Client(server) as client:
        tools = await client.list_tools()
        for tool in tools.tools:
            print(f"tool   {tool.name}({', '.join(tool.input_schema['properties'])}) -> {tool.output_schema['title']}")

        result = await client.call_tool("add_task", {"title": "Tag v1.2", "priority": "high"})
        print("ok    ", result.structured_content)

        result = await client.call_tool("add_task", {"title": "v2"})
        print("error ", result.is_error, result.content[0].text)

        result = await client.call_tool("complete_task", {"task_id": "T-9"})
        print("error ", result.is_error, result.content[0].text)

        try:  # a tools/call request with no tool name breaks the protocol, not the tool
            await client.session.send_request(types.Request(method="tools/call", params={"arguments": {}}), types.CallToolResult)
        except MCPError as error:
            print("raised", type(error).__name__, error.code, error.message)


if __name__ == "__main__":
    asyncio.run(main())
