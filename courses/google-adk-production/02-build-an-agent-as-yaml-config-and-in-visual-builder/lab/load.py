"""Load root_agent.yaml from Python and run one question through a Runner.

Run from this folder with GOOGLE_API_KEY set: python load.py "How do I roll back production?"
"""
import asyncio
import sys
from pathlib import Path

from google.adk import Runner
from google.adk.agents.config_agent_utils import from_config
from google.adk.sessions import InMemorySessionService
from google.genai import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # so the YAML's docs_config.tools.read_page imports, as under adk run


def load():
    """from_config validates the YAML against LlmAgent's fields and imports each tool by name."""
    return from_config(str(HERE / "docs_config" / "root_agent.yaml"))


def describe(event) -> str:
    parts = event.content.parts if event.content and event.content.parts else []
    what = [f"call {p.function_call.name}({dict(p.function_call.args)})" if p.function_call
            else f"result {p.function_response.name}" if p.function_response
            else repr(p.text[:40]) for p in parts if p.function_call or p.function_response or (p.text and not p.thought)]
    return f"{event.author:<15} {' + '.join(what)}"


async def ask(agent, question: str) -> list:
    sessions = InMemorySessionService()
    runner = Runner(app_name="docs_config", agent=agent, session_service=sessions)
    session = await sessions.create_session(app_name="docs_config", user_id="dev-1")
    message = types.Content(role="user", parts=[types.Part(text=question)])
    try:
        return [e async for e in runner.run_async(user_id="dev-1", session_id=session.id, new_message=message)]
    finally:
        await runner.close()


def main() -> None:
    agent = load()
    print(f"{type(agent).__name__} {agent.name} model={agent.model} tools={[t.__name__ for t in agent.tools]}")
    print(f"temperature={agent.generate_content_config.temperature} "
          f"thinking_level={agent.generate_content_config.thinking_config.thinking_level.value}")
    events = asyncio.run(ask(agent, sys.argv[1]))
    for event in events:
        print(describe(event))
    print("answer:", events[-1].content.parts[-1].text)


if __name__ == "__main__":
    main()
