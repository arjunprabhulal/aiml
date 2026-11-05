"""A docs assistant that calls tools: the model proposes calls, the application validates and runs them.
Run: python docs_tools.py"""
import json
from pathlib import Path
from typing import Annotated, Literal

import ollama
from pydantic import Field, TypeAdapter, ValidationError, validate_call

MODEL = "gemma4:e2b"
DOCS = {page.name: page.read_text() for page in sorted((Path(__file__).parent / "docs").glob("*.md"))}
Page = Literal["config.md", "deploy.md", "rollback.md", "tokens.md"]


@validate_call
def search_docs(query: Annotated[str, Field(min_length=2, description='Words to look for, such as "rollback".')]) -> list[dict]:
    """Search the docuctl docs and return matching page names with their titles."""
    words = {word.lower() for word in query.split()}
    hits = [(sum(word in text.lower() for word in words), name) for name, text in DOCS.items()]
    return [{"page": name, "title": DOCS[name].splitlines()[0].lstrip("# ")}
            for score, name in sorted(hits, reverse=True) if score]


@validate_call
def read_page(page: Annotated[Page, Field(description="A page name returned by search_docs.")]) -> str:
    """Return the full text of one docuctl docs page."""
    return DOCS[page]


TOOLS = {tool.__name__: tool for tool in (search_docs, read_page)}


def definition(tool) -> dict:
    """What the model sees: name, docstring and the Pydantic argument schema, enums included."""
    return {"type": "function", "function": {"name": tool.__name__, "description": tool.__doc__,
                                             "parameters": TypeAdapter(tool).json_schema()}}


def run_tool(name: str, arguments: dict, offered: set[str] | None = None) -> str:
    """The application's side of a tool call: only known tools, only valid arguments."""
    if offered is not None and name not in offered:
        return f"error: tool {name!r} was not offered in this request"
    if name not in TOOLS:
        return f"error: unknown tool {name!r}; available tools: {', '.join(TOOLS)}"
    try:
        return json.dumps(TOOLS[name](**arguments))
    except ValidationError as error:
        return f"error: invalid arguments for {name}: {error.errors()[0]['msg']}"


def answer(client: ollama.Client, question: str, max_rounds: int = 4, tools: list | None = None) -> list[str]:
    messages = [{"role": "system", "content": "You answer questions about docuctl. Use the tools, cite the page, and answer in at most two sentences."},
                {"role": "user", "content": question}]
    log = []
    definitions = [definition(tool) for tool in TOOLS.values()] if tools is None else tools
    offered = {item.__name__ if callable(item) else item["function"]["name"] for item in definitions}
    for _ in range(max_rounds):
        reply = client.chat(model=MODEL, messages=messages, tools=definitions, think=False,
                            options={"temperature": 0})
        messages.append(reply.message)
        if not reply.message.tool_calls:
            log.append(f"answer: {reply.message.content.strip()}")
            return log
        for call in reply.message.tool_calls:
            result = run_tool(call.function.name, dict(call.function.arguments), offered)
            log.append(f"call {call.function.name}({json.dumps(dict(call.function.arguments))}) -> {result[:90]}")
            messages.append({"role": "tool", "tool_name": call.function.name, "content": result})
    log.append(f"stopped: no answer after {max_rounds} rounds")
    return log


def main() -> None:
    client = ollama.Client()
    print("read_page schema:", json.dumps(definition(read_page)["function"]["parameters"]["properties"]))
    for question in ["How do I roll back production to r41?", "How long is a CI deploy token valid?"]:
        print(f"Q: {question}")
        for line in answer(client, question):
            print("  ", line)


if __name__ == "__main__":
    main()
