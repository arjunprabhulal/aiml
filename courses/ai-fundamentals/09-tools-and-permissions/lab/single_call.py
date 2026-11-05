"""Inspect one model response and validate its proposed read calls. No agent loop.
Run: python single_call.py
"""
import json
import ollama
from docs_tools import MODEL, definition, read_page, run_tool

QUESTION = "Read rollback.md from the docs. Use the read_page tool."


def call_once(client, question: str, tools: list | None = None) -> list[dict]:
    definitions = [definition(read_page)] if tools is None else tools
    offered = {item["function"]["name"] for item in definitions}
    reply = client.chat(model=MODEL, messages=[{"role": "user", "content": question}],
                        tools=definitions, think=False, options={"temperature": 0, "num_predict": 256})
    # No call is also a possible model response. Record it without executing anything.
    return [{"name": call.function.name, "arguments": dict(call.function.arguments),
             "result": run_tool(call.function.name, dict(call.function.arguments), offered)}
            for call in reply.message.tool_calls or []]


if __name__ == "__main__":
    print(json.dumps(call_once(ollama.Client(), QUESTION), indent=2))
