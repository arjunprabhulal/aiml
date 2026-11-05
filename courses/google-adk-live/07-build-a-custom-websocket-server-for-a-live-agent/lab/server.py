"""A FastAPI WebSocket bridge for a live agent: binary audio frames in and out, JSON events, a session cap."""
import asyncio
import anyio
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google.adk.agents import Agent, LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from live_harness import MODEL

APP = "voice_docs"
DOCS = (Path(__file__).parent / "docs/live-streaming.md").read_text()
log = logging.getLogger("voice_docs.server")


def build_agent(model=MODEL) -> Agent:
    return Agent(name="docs_helper", model=model, instruction=(
        "You are the docs assistant. Answer only from this page in one or two short spoken sentences.\n\n" + DOCS))


def create_app(agent: Agent, max_sessions: int = 2) -> FastAPI:
    app = FastAPI()
    runner = Runner(app_name=APP, agent=agent, session_service=InMemorySessionService())  # once, at startup
    active: set[tuple[str, str]] = set()
    app.state.active = active  # sessions with a running handler

    @app.websocket("/ws/{user_id}/{session_id}")
    async def live(websocket: WebSocket, user_id: str, session_id: str) -> None:
        await websocket.accept()
        key = (user_id, session_id)
        if key in active:
            await websocket.close(code=1008, reason="session already has a live connection")
            return
        if len(active) >= max_sessions:  # refuse here, before the Live API quota refuses for you
            await websocket.close(code=1013, reason="voice sessions full, try again shortly")
            return
        active.add(key)
        queue = LiveRequestQueue()  # one per connection, never reused
        run_config = RunConfig(response_modalities=["AUDIO"], session_resumption=types.SessionResumptionConfig())

        async def upstream() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                if message.get("bytes"):  # 16 kHz PCM from the microphone
                    queue.send_realtime(types.Blob(mime_type="audio/pcm;rate=16000", data=message["bytes"]))
                elif message.get("text"):
                    queue.send_content(types.Content(role="user", parts=[types.Part(text=message["text"])]))

        async def downstream() -> None:
            async for event in runner.run_live(user_id=user_id, session_id=session_id,
                                               live_request_queue=queue, run_config=run_config):
                parts = event.content.parts if event.content else []
                for part in parts:
                    if part.inline_data:  # 24 kHz PCM as a binary frame: no base64 inflation
                        await websocket.send_bytes(part.inline_data.data)
                if not (parts and all(p.inline_data for p in parts)):
                    await websocket.send_text(event.model_dump_json(
                        exclude_none=True, by_alias=True, exclude={"content": {"parts": {"__all__": {"inline_data"}}}}))

        tasks = []
        try:
            if not await runner.session_service.get_session(app_name=APP, user_id=user_id, session_id=session_id):
                await runner.session_service.create_session(app_name=APP, user_id=user_id, session_id=session_id)
            tasks = [asyncio.create_task(upstream()), asyncio.create_task(downstream())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            failure = next((t.exception() for t in done if t.exception()
                            and not isinstance(t.exception(), WebSocketDisconnect)), None)
            if failure:  # tell the client why, instead of a silent close
                log.error("live session %s failed: %r", session_id, failure)
                await websocket.close(code=1011, reason=f"{type(failure).__name__}: {failure}"[:120])
        finally:
            queue.close()  # always: an unclosed queue can strand a Live API session against your quota
            for task in tasks:
                if not task.done():
                    task.cancel()
            active.discard(key)
            # ASGI cancellation must not interrupt the cleanup of sibling tasks.
            with anyio.CancelScope(shield=True):
                await asyncio.gather(*tasks, return_exceptions=True)

    return app


app = create_app(build_agent())
