"""Run both agents against Ollama several times and save what happened. Run: python record_runs.py

Writes agent-runs.json (discovery, the first trial's model turns for offline replay, every
trial's tool calls, timings and versions) and agent-output.txt (the first trial as printed).
Needs Ollama with gemma4:e2b and TASKS_SERVER_PYTHON pointing at the server's Python.
"""
import asyncio
import contextlib
import importlib.metadata
import io
import json
import os
import platform
import subprocess
import time
import urllib.request

import agent_adk
import agent_langgraph

QUESTIONS = ["Close the docs task.", "Mark task T-9 as done."]
TRIALS = 3
PACKAGES = ["google-adk", "litellm", "langchain", "langgraph", "langchain-mcp-adapters", "langchain-ollama", "mcp"]
FRAMEWORKS = {"adk": agent_adk, "langgraph": agent_langgraph}


def printed(function, *args) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        function(*args)
    return buffer.getvalue()


def model_turns(framework, result) -> list:
    if framework == "adk":
        return [e.content.model_dump(mode="json", exclude_none=True) for e in result if e.content and e.content.role == "model"]
    return [{"content": m.content, "tool_calls": [{"name": c["name"], "args": c["args"]} for c in m.tool_calls]}
            for m in result if m.type == "ai"]


def tool_results(framework, result) -> list:
    """What each framework hands back to the model after a tool call."""
    if framework == "adk":
        return [part.function_response.response for event in result if event.content
                for part in event.content.parts if part.function_response]
    return [{"status": m.status, "content": m.content, "artifact": m.artifact} for m in result if m.type == "tool"]


async def declarations() -> dict:
    """The complete_task definition as each framework gives it to the model."""
    adk = {tool.name: tool for tool in await agent_adk.toolset.get_tools()}["complete_task"]._get_declaration()
    await agent_adk.toolset.close()
    async with agent_langgraph.client.session("tasks") as session:
        langgraph = {tool.name: tool for tool in await agent_langgraph.load_mcp_tools(session)}["complete_task"]
    return {"adk": adk.model_dump(mode="json", exclude_none=True),
            "langgraph": {"name": langgraph.name, "description": langgraph.description, "args_schema": langgraph.args_schema}}


def calls(transcript: str) -> list:
    return [line.split(None, 1)[1] for line in transcript.splitlines() if line.startswith(("call", "result"))]


async def record() -> tuple[dict, list]:
    discovery = {}
    for name, module in FRAMEWORKS.items():
        with contextlib.redirect_stdout(io.StringIO()) as buffer:
            await module.discover()
        discovery[name] = buffer.getvalue()
    runs = []
    for framework, module in FRAMEWORKS.items():
        for question in QUESTIONS:
            trials = []
            for _ in range(TRIALS):
                started = time.perf_counter()
                result = await module.ask(question)
                transcript = printed(module.show, result)
                trials.append({"seconds": round(time.perf_counter() - started, 2), "calls": calls(transcript),
                               "transcript": transcript, "model_turns": model_turns(framework, result),
                               "tool_results": tool_results(framework, result)})
            runs.append({"framework": framework, "question": question, "trials": trials})
    return discovery | {"declarations": await declarations()}, runs


def main() -> None:
    with urllib.request.urlopen("http://localhost:11434/api/tags") as response:
        digest = next(m["digest"] for m in json.load(response)["models"] if m["name"] == "gemma4:e2b")
    server_mcp = subprocess.run([os.environ["TASKS_SERVER_PYTHON"], "-c", "import importlib.metadata as m; print(m.version('mcp'))"],
                                capture_output=True, text=True, check=True).stdout.strip()
    discovery, runs = asyncio.run(record())
    record_file = {
        "model": {"ollama_tag": "gemma4:e2b", "digest": digest, "options": "Ollama defaults"},
        "versions": {"python": platform.python_version(), **{p: importlib.metadata.version(p) for p in PACKAGES}, "server mcp": server_mcp},
        "discovery": discovery,
        "runs": runs,
    }
    with open("agent-runs.json", "w", encoding="utf-8") as out:
        json.dump(record_file, out, indent=2, ensure_ascii=False)
        out.write("\n")
    with open("agent-output.txt", "w", encoding="utf-8") as out:
        for name in FRAMEWORKS:
            out.write(f"$ python agent_{name}.py --tools\n{discovery[name]}\n")
        for run in runs:
            out.write(f"$ python agent_{run['framework']}.py \"{run['question']}\"\n{run['trials'][0]['transcript']}\n")


if __name__ == "__main__":
    main()
