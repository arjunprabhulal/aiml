"""The two-task bridge as adk.dev/live/custom-server writes it, with asyncio.gather. Kept to show its hang-up bug."""
import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

open_handlers: set[str] = set()  # sessions whose handler has not returned yet


def create_gather_app(agent) -> FastAPI:
    app = FastAPI()
    runner = Runner(app_name="voice_docs", agent=agent, session_service=InMemorySessionService())

    @app.websocket("/ws/{user_id}/{session_id}")
    async def live(websocket: WebSocket, user_id: str, session_id: str) -> None:
        await websocket.accept()
        open_handlers.add(session_id)
        await runner.session_service.create_session(app_name="voice_docs", user_id=user_id, session_id=session_id)
        queue = LiveRequestQueue()

        async def upstream() -> None:
            try:
                while True:
                    queue.send_realtime(types.Blob(mime_type="audio/pcm;rate=16000", data=await websocket.receive_bytes()))
            except WebSocketDisconnect:
                pass  # returns normally, so gather keeps waiting for downstream

        async def downstream() -> None:
            async for event in runner.run_live(user_id=user_id, session_id=session_id, live_request_queue=queue,
                                               run_config=RunConfig(response_modalities=["AUDIO"])):
                await websocket.send_text(event.model_dump_json(exclude_none=True, by_alias=True))

        try:
            await asyncio.gather(upstream(), downstream(), return_exceptions=True)
        finally:
            queue.close()
            open_handlers.discard(session_id)

    return app
