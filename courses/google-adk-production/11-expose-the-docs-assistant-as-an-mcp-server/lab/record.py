"""Record MCP clients talking to the docs assistant's MCP server over stdio, on Gemini.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes recorded-runs.json and run-output.txt. The key is passed to the server process, never recorded.
"""
import asyncio
import json
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

import release_bot  # noqa: E402

HERE = Path(__file__).resolve().parent
FIRST = "I'm on docuctl 1.x. How do I roll back production to r41?"
FOLLOW_UP = "And how do I list the releases of production?"


def params(with_key: bool = True) -> StdioServerParameters:
    env = {"GOOGLE_API_KEY": os.environ["GOOGLE_API_KEY"]} if with_key else None
    return StdioServerParameters(command=sys.executable, args=[str(HERE / "server.py")], env=env, cwd=str(HERE))


def text_of(result) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


async def connection(questions: list[str], with_key: bool = True) -> dict:
    """One MCP connection: initialize, list tools, then call the agent tool once per question."""
    async with stdio_client(params(with_key)) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        tools = (await session.list_tools()).tools
        calls = []
        for question in questions:
            start = time.perf_counter()
            result = await session.call_tool(tools[0].name, {"request": question})
            calls.append({"request": question, "is_error": result.isError, "text": text_of(result),
                          "seconds": round(time.perf_counter() - start, 1)})
    return {"server": {"name": init.serverInfo.name, "instructions": init.instructions,
                       "capabilities": sorted(k for k, v in init.capabilities.model_dump().items() if v)},
            "tools": [t.model_dump(mode="json", exclude_none=True) for t in tools], "calls": calls}


async def main() -> None:
    first = await connection([FIRST, FOLLOW_UP])
    fresh = await connection([FOLLOW_UP])
    no_key = await connection([FIRST], with_key=False)
    bot = await release_bot.record(timeout=60)
    bot_default_timeout = await release_bot.record(timeout=None)
    record = {"model": release_bot.MODEL, "same_connection": first, "new_connection": fresh,
              "failures": {"no_key": no_key, "default_timeout": bot_default_timeout}, "release_bot": bot}
    text = json.dumps(record, indent=2)
    assert os.environ["GOOGLE_API_KEY"] not in text
    (HERE / "recorded-runs.json").write_text(text + "\n", encoding="utf-8")
    tool = first["tools"][0]
    lines = [f"server {first['server']['name']}: {first['server']['instructions']}",
             f"tool   {tool['name']}({', '.join(tool['inputSchema']['properties'])}): {tool['description']}", ""]
    for label, run in [("connection 1", first), ("connection 2", fresh), ("no GOOGLE_API_KEY in the server env", no_key)]:
        lines.append(f"# {label}")
        for c in run["calls"]:
            lines += [f"> {c['request']}", f"{'error ' if c['is_error'] else 'answer'} {c['text'][:260]}  ({c['seconds']}s)"]
        lines.append("")
    for label, run in [("release_bot through McpToolset, timeout=60", bot),
                       ("release_bot through McpToolset, default timeout", bot_default_timeout)]:
        lines += [f"# {label}", f"> {run['question']}"]
        lines += [f"call   {c['name']} {json.dumps(c['args'])[:160]}" for c in run["calls"]]
        lines += [f"result {json.dumps(r)[:220]}" for r in run["results"]]
        lines += ["answer " + run["answer"].replace("\n", " ")[:300], ""]
    (HERE / "run-output.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
