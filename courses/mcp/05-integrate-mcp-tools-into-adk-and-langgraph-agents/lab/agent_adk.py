"""A Google ADK agent that uses the tasks MCP server.

Run: python agent_adk.py --tools                  (list what the toolset discovered)
     python agent_adk.py "Which tasks are open?"  (needs Ollama with gemma4:e2b)
TASKS_SERVER_PYTHON is the Python that has mcp 2.3.0 installed for tasks_server.py.
"""
import asyncio
import os
import sys
from pathlib import Path

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

tasks_server = StdioServerParameters(
    command=os.environ.get("TASKS_SERVER_PYTHON", sys.executable),
    args=[str(Path(__file__).with_name("tasks_server.py"))],
)
toolset = McpToolset(connection_params=StdioConnectionParams(server_params=tasks_server))

root_agent = Agent(
    name="tasks_agent",
    model=LiteLlm(model="ollama_chat/gemma4:e2b"),
    instruction="You manage a software project's task tracker. Use the tools to read and change it.",
    tools=[toolset],
)


async def discover() -> None:
    """Print each tool as ADK declares it to the model."""
    for tool in await toolset.get_tools():
        schema = tool._get_declaration().parameters_json_schema
        print("tool  ", tool.name, schema.get("required", []), list(schema["properties"]))
    await toolset.close()


async def ask(question: str, agent: Agent = root_agent) -> list:
    """Run one question through the agent and return every event."""
    runner = InMemoryRunner(agent=agent, app_name="tasks")
    session = await runner.session_service.create_session(app_name="tasks", user_id="dev")
    message = types.Content(role="user", parts=[types.Part(text=question)])
    events = [event async for event in runner.run_async(user_id="dev", session_id=session.id, new_message=message)]
    await runner.close()
    return events


def show(events: list) -> None:
    for event in events:
        for part in event.content.parts if event.content else []:
            if part.function_call:
                print("call  ", part.function_call.name, part.function_call.args)
            elif part.function_response:
                response = part.function_response.response
                print("result", "error" if response.get("isError") else "ok", response.get("structuredContent") or response["content"][0]["text"])
            elif part.text and not part.thought:
                print("answer", part.text.strip())


if __name__ == "__main__":
    if sys.argv[1] == "--tools":
        asyncio.run(discover())
    else:
        show(asyncio.run(ask(sys.argv[1])))
