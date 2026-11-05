"""A LangGraph agent that uses the tasks MCP server.

Run: python agent_langgraph.py --tools                  (list what the adapter loaded)
     python agent_langgraph.py "Which tasks are open?"  (needs Ollama with gemma4:e2b)
TASKS_SERVER_PYTHON is the Python that has mcp 2.3.0 installed for tasks_server.py.
"""
import asyncio
import os
import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_ollama import ChatOllama

client = MultiServerMCPClient({
    "tasks": {
        "transport": "stdio",
        "command": os.environ.get("TASKS_SERVER_PYTHON", sys.executable),
        "args": [str(Path(__file__).with_name("tasks_server.py"))],
    }
})


async def discover() -> None:
    """Print each tool as the adapter gives it to the model."""
    async with client.session("tasks") as session:
        for tool in await load_mcp_tools(session):
            print("tool  ", tool.name, tool.args_schema.get("required", []), list(tool.args_schema["properties"]))


async def ask(question: str, model=None) -> list:
    """Run one question through the agent in one MCP session and return every message."""
    async with client.session("tasks") as session:
        agent = create_agent(
            model or ChatOllama(model="gemma4:e2b"),
            await load_mcp_tools(session),
            system_prompt="You manage a software project's task tracker. Use the tools to read and change it.",
        )
        result = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})
    return result["messages"]


def show(messages: list) -> None:
    for message in messages:
        for call in getattr(message, "tool_calls", []):
            print("call  ", call["name"], call["args"])
        if message.type == "tool":
            print("result", message.status, message.artifact.get("structured_content") if message.artifact else message.text)
        elif message.type == "ai" and message.text:
            print("answer", message.text.strip())


if __name__ == "__main__":
    if sys.argv[1] == "--tools":
        asyncio.run(discover())
    else:
        show(asyncio.run(ask(sys.argv[1])))
