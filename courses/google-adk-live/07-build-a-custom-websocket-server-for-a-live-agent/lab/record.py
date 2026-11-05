"""Record the bridge on a local port: one spoken question, a refused second caller, a model error, a hang-up."""
import asyncio
import base64
import json
from pathlib import Path

import uvicorn
import websockets

from client import ask, transcript
from live_harness import RecordingGemini, environment, MODEL
import gather_bridge
from server import build_agent, create_app

HERE = Path(__file__).parent
WAV = HERE / "question.wav"


async def serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=3))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    return server, task


async def with_server(model_id, port, body, max_sessions=2, factory=None):
    model = RecordingGemini(model=model_id, connections=[])
    app = factory(build_agent(model)) if factory else create_app(build_agent(model), max_sessions=max_sessions)
    server, task = await serve(app, port)
    try:
        result = await body(f"ws://127.0.0.1:{port}/ws/dev")
        if isinstance(result, dict) and "first_frame" in result:  # a hang-up: which handlers are still running
            still = app.state.active if hasattr(app.state, "active") else gather_bridge.open_handlers
            result["handlers_open_after_10_s"] = sorted(still)
    finally:
        server.should_exit = True
        await task
    return result, model.connections


async def hang_up(base):
    """Ask, wait for the answer to finish, then hang up while the agent is idle."""
    async with websockets.connect(f"{base}/hang-up") as ws:
        pcm = WAV.read_bytes()[44:] + bytes(32000)
        for start in range(0, len(pcm), 3200):
            await ws.send(pcm[start:start + 3200])
            await asyncio.sleep(0.1)
        async for frame in ws:
            if isinstance(frame, str) and json.loads(frame).get("turnComplete"):
                break
    await asyncio.sleep(10)  # give the server time to notice the hang-up
    return {"first_frame": "hung up after turnComplete"}


async def main():
    answered, connections = await with_server(MODEL, 8770, lambda base: ask(f"{base}/call-1", WAV))
    audio, events = answered["audio_bytes"], answered["events"]
    answered.update(heard=transcript(events, "inputTranscription"), answer=transcript(events),
                    base64_bytes=len(base64.b64encode(bytes(audio))), connections=connections)
    print(f"[spoken question] heard={answered['heard']!r} said={answered['answer']!r}")
    print(f"  frames={answered['frames']} audio={audio} bytes, as base64 JSON: {answered['base64_bytes']} bytes")

    async def two_callers(base):
        first = asyncio.create_task(ask(f"{base}/call-a", WAV))
        await asyncio.sleep(0.5)
        second = await ask(f"{base}/call-b", WAV, timeout=10)
        return {"first": await first, "second": second}
    full, _ = await with_server(MODEL, 8771, two_callers, max_sessions=1)
    print(f"[second caller, cap 1] closed={full['second'].get('closed')} first said={transcript(full['first']['events'])!r}")

    failed, _ = await with_server("gemini-3.8-flash", 8772, lambda base: ask(f"{base}/call-x", WAV, timeout=20))
    print(f"[standard model behind the bridge] closed={failed.get('closed')} events={len(failed['events'])}")

    hung, hung_connections = await with_server(MODEL, 8773, hang_up)
    hung["connections"] = hung_connections

    gathered, gathered_connections = await with_server(MODEL, 8774, hang_up, factory=gather_bridge.create_gather_app)
    gathered["connections"] = gathered_connections
    print(f"[client hangs up, gather bridge] handlers still open after 10 s: {gathered['handlers_open_after_10_s']}")
    print(f"[client hangs up, this bridge] handlers still open after 10 s: {hung['handlers_open_after_10_s']}")

    record = {"gather_hang_up": gathered, "environment": environment(), "answered": answered, "session_cap": full, "model_error": failed, "hang_up": hung}
    (HERE / "server-run.json").write_text(json.dumps(record, indent=1) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
