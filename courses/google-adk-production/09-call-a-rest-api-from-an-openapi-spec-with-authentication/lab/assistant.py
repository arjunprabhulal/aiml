"""The docs assistant answers release questions by calling the docuctl release API from its OpenAPI spec.

OpenAPIToolset turns each operation in the spec into a RestApiTool. The API key travels as an
auth credential that ADK adds to each HTTP request rather than a function argument.
"""
import asyncio
import json
import os
import sys

import httpx
from google.adk import Agent, Runner
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.adk.tools.openapi_tool import OpenAPIToolset
from google.adk.tools.openapi_tool.auth.auth_helpers import token_to_scheme_credential
from google.genai import types

# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
API_URL = os.environ.get("SHIP_API_URL", "http://127.0.0.1:8766")
READ_ONLY = ["list_releases", "get_release"]  # generated names: operationId in snake_case


def load_spec(url: str = API_URL) -> dict:
    """Fetch the spec the service publishes, and pin the server it should be called on."""
    spec = httpx.get(f"{url}/openapi.json", timeout=5).raise_for_status().json()
    spec["servers"] = [{"url": url}]  # FastAPI omits servers; without one, ADK has no base URL
    return spec


def request_id(context: ReadonlyContext) -> dict[str, str]:
    """Tag every API call with the ADK invocation, so server logs join up with agent traces."""
    return {"X-Request-ID": context.invocation_id}


def release_tools(spec: dict, api_key: str, tool_filter: list[str] | None = READ_ONLY) -> OpenAPIToolset:
    auth_scheme, auth_credential = token_to_scheme_credential("apikey", "header", "X-Ship-Key", api_key)
    return OpenAPIToolset(spec_dict=spec, auth_scheme=auth_scheme, auth_credential=auth_credential,
                          tool_filter=tool_filter, header_provider=request_id)


INSTRUCTION = """You answer developers' questions about docuctl releases.
Use the release API tools to look up releases; never guess a release name or status.
You cannot change an environment. If asked to roll back, give the docuctl command instead:
docuctl rollback --env <env> --to <release>. Keep answers under 80 words."""


def make_agent(tools: OpenAPIToolset) -> Agent:
    return Agent(
        name="docs_assistant",
        model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
        instruction=INSTRUCTION,
        tools=[tools],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
    )


async def ask(runner: Runner, session_id: str, text: str) -> list:
    message = types.Content(role="user", parts=[types.Part(text=text)])
    return [e async for e in runner.run_async(user_id="dana", session_id=session_id, new_message=message)]


async def main(question: str) -> None:
    tools = release_tools(load_spec(), os.environ["SHIP_API_KEY"])
    print("tools:", [t.name for t in await tools.get_tools()])
    runner = Runner(app_name="docs", agent=make_agent(tools), session_service=InMemorySessionService(),
                    auto_create_session=True)
    for event in await ask(runner, "s1", question):
        for call in event.get_function_calls():
            print("call  ", call.name, json.dumps(call.args))
        for result in event.get_function_responses():
            print("result", result.name, json.dumps(result.response)[:200])
        if event.is_final_response() and event.content:
            print("answer", "".join(p.text or "" for p in event.content.parts if not p.thought))
    await runner.close()


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:])))
