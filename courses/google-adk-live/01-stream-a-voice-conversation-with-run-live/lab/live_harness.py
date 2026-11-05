"""Drive run_live, keep the event fields a reader needs, and record or replay the Live API traffic.

RecordingGemini wraps the real Live connection and logs what ADK sends and what the model
returns (audio is logged as a byte count). ReplayLive plays that log back through ADK's own
run_live loop, so the tests exercise ADK's tool execution, callbacks and session writes offline.
"""
import asyncio
import base64
import contextlib
import os
import wave
from importlib.metadata import version

from google.adk.agents import LiveRequestQueue
from google.adk.models import BaseLlm, Gemini, LlmResponse
from google.adk.models.base_llm_connection import BaseLlmConnection
from google.genai import types

# Current course Live model. Override with LIVE_MODEL.
MODEL = os.getenv("LIVE_MODEL", "gemini-3.8-live")
RATE_IN, CHUNK_MS = 16000, 100
PACE = 1.0  # seconds of wall time per second of audio; the tests set 0


def summarize(event) -> dict:
    """One event as the fields this course prints. Audio becomes a byte count."""
    row = {"author": event.author}
    for flag in ("partial", "turn_complete", "interrupted"):
        if getattr(event, flag):
            row[flag] = True
    for side in ("input_transcription", "output_transcription"):
        part = getattr(event, side)
        if part and (part.text or part.finished):
            row[side] = {"text": part.text or "", "finished": bool(part.finished)}
    for part in (event.content.parts or []) if event.content else []:
        if part.inline_data:
            row["audio_bytes"] = row.get("audio_bytes", 0) + len(part.inline_data.data or b"")
            row["mime_type"] = part.inline_data.mime_type
        elif part.text and not part.thought:
            row["text"] = row.get("text", "") + part.text
        if part.function_call:
            row.setdefault("calls", []).append({"name": part.function_call.name, "args": part.function_call.args})
        if part.function_response:
            row.setdefault("responses", []).append(
                {"name": part.function_response.name, "response": part.function_response.response})
    if event.usage_metadata and event.usage_metadata.total_token_count:
        row["total_tokens"] = event.usage_metadata.total_token_count
    if event.error_code:
        row["error"] = f"{event.error_code}: {event.error_message}"
    if event.live_session_resumption_update:
        row["resumption_update"] = bool(event.live_session_resumption_update.new_handle)
    if event.actions and event.actions.transfer_to_agent:
        row["transfer_to_agent"] = event.actions.transfer_to_agent
    return row


def read_pcm(path) -> bytes:
    """The PCM frames of a 16 kHz, 16-bit mono WAV file; any other format is refused."""
    with wave.open(str(path)) as clip:
        shape = (clip.getframerate(), clip.getsampwidth(), clip.getnchannels())
        if shape != (RATE_IN, 2, 1):
            raise ValueError(f"{path}: {shape} is not (16000 Hz, 16-bit, mono)")
        return clip.readframes(clip.getnframes())


def say_text(text):
    async def send(queue):
        queue.send_content(types.Content(role="user", parts=[types.Part(text=text)]))
    return send


def say_audio(pcm, mime_type="audio/pcm;rate=16000", silence_s=1.0):
    """Stream a clip in 100 ms chunks, then silence so voice activity detection ends the turn."""
    step = RATE_IN * 2 * CHUNK_MS // 1000
    data = pcm + bytes(int(RATE_IN * 2 * silence_s))

    async def stream(queue):
        for start in range(0, len(data), step):
            queue.send_realtime(types.Blob(mime_type=mime_type, data=data[start:start + step]))
            await asyncio.sleep(PACE * CHUNK_MS / 1000)

    async def send(queue):
        asyncio.get_running_loop().create_task(stream(queue))
    return send


async def talk(runner, session_id, run_config, turns, user_id="dev", timeout=90, queue=None):
    """Send each turn after the previous turn completes; return the summarized events."""
    queue = queue or LiveRequestQueue()
    rows, pending = [], list(turns)

    async def loop():
        if pending:
            await pending.pop(0)(queue)
        async for event in runner.run_live(user_id=user_id, session_id=session_id,
                                           live_request_queue=queue, run_config=run_config):
            rows.append(summarize(event))
            if event.turn_complete:
                if not pending:
                    break
                await pending.pop(0)(queue)
    try:
        await asyncio.wait_for(loop(), timeout)
    except asyncio.TimeoutError as error:
        error.rows = rows  # keep what arrived before the timeout
        raise
    finally:
        queue.close()
    return rows


def wait_for_turn():
    """A turn that sends nothing: wait for the model to speak on its own, for example a tool result."""
    async def send(queue):
        return None
    return send


def spoken(rows, side="output_transcription") -> str:
    """The transcript of one side: the finished fragments joined in order."""
    return "".join(r[side]["text"] for r in rows if side in r and not r.get("partial")).strip()


def environment() -> dict:
    return {"google-adk": version("google-adk"), "google-genai": version("google-genai"), "model": MODEL}


def _dump(response: LlmResponse) -> dict:
    data = response.model_dump(mode="json", exclude_none=True)
    for part in data.get("content", {}).get("parts", []):
        part.pop("thought_signature", None)
        if "inline_data" in part and isinstance(part["inline_data"].get("data"), str):
            part["inline_data"]["data"] = len(base64.urlsafe_b64decode(part["inline_data"]["data"] + "=="))
    data.pop("live_session_id", None)
    return data


def _load(data: dict) -> LlmResponse:
    data = {**data, "content": {**data["content"]}} if "content" in data else dict(data)
    parts = []
    for part in data.get("content", {}).get("parts", []):
        if isinstance(part.get("inline_data", {}).get("data"), int):
            part = {**part, "inline_data": {**part["inline_data"], "data": bytes(part["inline_data"]["data"])}}
        parts.append(part)
    if "content" in data:
        data["content"]["parts"] = parts
    return LlmResponse.model_validate(data)


class _Recorded(BaseLlmConnection):
    def __init__(self, inner, traffic):
        self.inner, self.traffic = inner, traffic

    def _sent(self, kind, **fields):
        last = self.traffic[-1] if self.traffic else {}
        if kind == "realtime" and last.get("sent") == "realtime" and last["mime_type"] == fields["mime_type"]:
            last["chunks"] += 1
            last["bytes"] += fields["bytes"]
        else:
            self.traffic.append({"sent": kind, **fields} | ({"chunks": 1} if kind == "realtime" else {}))

    async def send_history(self, history):
        self._sent("history", turns=[{"role": c.role, "text": "".join(p.text or "" for p in c.parts or [])[:120]}
                                     for c in history])
        await self.inner.send_history(history)

    async def send_content(self, content):
        await self._send_content(content)

    async def _send_content(self, content, *, partial=False):
        parts = content.parts or []
        self._sent("content", text="".join(p.text or "" for p in parts),
                   function_responses=[p.function_response.name for p in parts if p.function_response])
        await self.inner._send_content(content, partial=partial)

    async def send_realtime(self, blob):
        mime = getattr(blob, "mime_type", None) or type(blob).__name__
        self._sent("realtime", mime_type=mime, bytes=len(getattr(blob, "data", b"") or b""))
        await self.inner.send_realtime(blob)

    async def receive(self):
        async for response in self.inner.receive():
            self.traffic.append({"received": _dump(response)})
            yield response

    async def close(self):
        self.traffic.append({"sent": "close"})
        await self.inner.close()


class RecordingGemini(Gemini):
    """A Gemini model that logs each live connection: its config and its traffic."""

    connections: list = []

    @contextlib.asynccontextmanager
    async def connect(self, llm_request):
        declarations = [d for tool in llm_request.config.tools or [] for d in getattr(tool, "function_declarations", None) or []]
        log = {"model": llm_request.model, "traffic": [],
               "tools": [{"name": d.name, "behavior": d.behavior.value if d.behavior else None} for d in declarations]}
        self.connections.append(log)
        async with super().connect(llm_request) as connection:
            # Read the config after Gemini.connect has applied the agent-level voice and instruction.
            config = llm_request.live_connect_config.model_dump(mode="json", exclude_none=True)
            for private in ("system_instruction", "http_options", "tools"):
                config.pop(private, None)
            log["config"] = config
            yield _Recorded(connection, log["traffic"])


class _Replay(BaseLlmConnection):
    def __init__(self, traffic):
        self.traffic, self.index, self.sent, self.closed = traffic, 0, 0, False
        self.changed = asyncio.Event()
        self.received = []  # what ADK sent, for assertions

    def _note(self, item, weight=1):
        self.received.append(item)
        self.sent += weight
        self.changed.set()

    async def send_history(self, history):
        self._note(("history", len(history)))

    async def send_content(self, content):
        await self._send_content(content)

    async def _send_content(self, content, *, partial=False):
        self._note(("content", content))

    async def send_realtime(self, blob):
        self._note(("realtime", getattr(blob, "mime_type", type(blob).__name__)))

    async def receive(self):
        needed = sum(e.get("chunks", 1) for e in self.traffic[:self.index] if "sent" in e)
        while self.index < len(self.traffic):
            entry = self.traffic[self.index]
            self.index += 1
            if "sent" in entry:
                needed += entry.get("chunks", 1) if entry["sent"] != "close" else 0
                continue
            while self.sent < needed and not self.closed:
                self.changed.clear()
                await self.changed.wait()
            if self.closed:
                return
            if "raise" in entry:
                raise entry["raise"]
            yield _load(entry["received"])
        while not self.closed:  # an idle open connection
            self.changed.clear()
            await self.changed.wait()

    async def close(self):
        self.closed = True
        self.changed.set()


class ReplayLive(BaseLlm):
    """Plays recorded connections back in order; refuses a connection it has no recording for."""

    connections: list
    opened: list = []

    async def generate_content_async(self, llm_request, stream=False):
        raise NotImplementedError("ReplayLive only replays run_live connections")
        yield  # pragma: no cover

    @contextlib.asynccontextmanager
    async def connect(self, llm_request):
        if not self.connections:
            raise LookupError("no recorded live connection left")
        replay = _Replay(self.connections.pop(0)["traffic"])
        self.opened.append((llm_request, replay))
        yield replay
