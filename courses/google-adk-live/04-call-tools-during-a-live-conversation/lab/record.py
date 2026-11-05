"""Record current Live tool runs; optionally include the historical model negative control."""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from google import genai
from google.genai import types

from live_harness import RecordingGemini, environment, MODEL, PACE, read_pcm, say_audio, say_text, spoken, talk, wait_for_turn
from live_tools import TOOLS_MODEL, build_agent

HERE = Path(__file__).parent
# Explicit historical negative control, not the runnable agent default.
HISTORICAL_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
from google.adk.agents.run_config import RunConfig

RUN_CONFIG = RunConfig(response_modalities=["AUDIO"])
LOOKUP_CONFIG = RunConfig(response_modalities=["AUDIO"], realtime_input_config=types.RealtimeInputConfig(
    automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)))


def read_page(name: str) -> dict:
    """Return the text of one docs page.

    Args:
      name: The page file name, for example "tools.md".
    """
    return {"name": name, "text": (HERE / "docs" / name).read_text()}


async def run(name, turns, agent_factory=build_agent, model_id=TOOLS_MODEL, timeout=90, run_config=RUN_CONFIG):
    model = RecordingGemini(model=model_id, connections=[])
    runner = Runner(app_name="voice_docs", agent=agent_factory(model), session_service=InMemorySessionService())
    session = await runner.session_service.create_session(app_name="voice_docs", user_id="dev")
    entry = {"name": name}
    try:
        rows = await talk(runner, session.id, run_config, turns, timeout=timeout)
    except asyncio.TimeoutError as error:
        rows, entry["error"] = error.rows, f"TimeoutError: no further turn within {timeout} s"
    except Exception as error:
        message = str(error).splitlines()[0].replace(str(HERE) + "/", "")  # keep local paths out of the record
        rows, entry["error"] = [], f"{type(error).__name__}: {message[:240]}"
    entry.update(events=rows, answer=spoken(rows), connections=model.connections)
    calls = [c["name"] for r in rows for c in r.get("calls", [])]
    print(f"[{name}] calls={calls} said={entry['answer'][:200]!r}" + (f" error={entry['error']}" if "error" in entry else ""))
    return entry


def push_to_talk(pcm):
    """Send one finite question with the same explicit activity signals as the media lesson."""
    async def send(queue):
        queue.send_activity_start()
        for start in range(0, len(pcm), 3200):
            queue.send_realtime(types.Blob(mime_type="audio/pcm;rate=16000", data=pcm[start:start + 3200]))
            await asyncio.sleep(PACE * 0.1)
        queue.send_activity_end()
    return send


def page_reader(model):
    return Agent(name="docs_helper", model=model, tools=[read_page],
                 instruction="You are the docs assistant. Use read_page to read pages. Answer in one short sentence.")


async def raw_tool_call(model_id, timeout=25):
    """Without ADK: which server messages follow a tool call on this model."""
    declaration = types.FunctionDeclaration(name="search_docs", description="Search the docs pages.", parameters=types.Schema(
        type="OBJECT", properties={"query": types.Schema(type="STRING")}, required=["query"]))
    config = types.LiveConnectConfig(response_modalities=["AUDIO"], system_instruction="Use search_docs to look facts up.",
                                     tools=[types.Tool(function_declarations=[declaration])])
    seen = []
    async with genai.Client().aio.live.connect(model=model_id, config=config) as live:
        await live.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=LOOKUP)]))

        async def receive():
            async for message in live.receive():
                if message.tool_call:
                    seen.append("tool_call")
                if message.server_content and message.server_content.turn_complete:
                    seen.append("turn_complete")
                    return
        try:
            await asyncio.wait_for(receive(), timeout)
        except asyncio.TimeoutError:
            seen.append(f"nothing more in {timeout} s")
    print(f"[raw Live API, {model_id}] {seen}")
    return {"model": model_id, "messages": seen}


LOOKUP = "How long does a Live API connection stay open? Look it up."


async def main(include_historical_models=False):
    started_at = datetime.now(timezone.utc).isoformat()
    runs = [
        await run("blocking lookup", [push_to_talk(read_pcm(HERE / "lookup.wav"))], run_config=LOOKUP_CONFIG),
        await run("streaming link check, then stop", [say_text("Check the links in the docs pages."),
                                                      wait_for_turn(), say_text("Never mind, stop the link check.")], timeout=60),
        await run("scheduled export on current Live model",
                  [say_text("Start the page index export. While it runs, tell me the input sample rate."), wait_for_turn()], timeout=60),
        await run("tool raises an exception", [say_text("Read the page deploy.md.")], agent_factory=page_reader, timeout=40),
    ]
    raw = [await raw_tool_call(TOOLS_MODEL)]
    if include_historical_models:
        runs.append(await run("tools on Gemini 2.5 Flash Live", [say_text(LOOKUP)], model_id=HISTORICAL_MODEL, timeout=40))
        raw.append(await raw_tool_call(HISTORICAL_MODEL))
    (HERE / "tools-run.json").write_text(json.dumps({"recorded_at": started_at, "environment": environment() | {"tools_model": TOOLS_MODEL},
                                                     "runs": runs, "raw_tool_call": raw}, indent=1) + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-historical-models", action="store_true",
                        help="Also rerun the explicitly historical Gemini 2.5 negative control")
    asyncio.run(main(parser.parse_args().include_historical_models))
