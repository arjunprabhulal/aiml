"""A test client: stream a WAV file as binary 100 ms frames and collect JSON events and audio bytes."""
import asyncio
import json

import websockets

from live_harness import read_pcm


async def ask(url: str, wav_path, silence_s: float = 1.0, timeout: float = 60) -> dict:
    pcm = read_pcm(wav_path) + bytes(int(16000 * 2 * silence_s))
    result = {"events": [], "audio_bytes": 0, "frames": {"binary": 0, "text": 0}}
    async with websockets.connect(url) as ws:
        async def send():
            for start in range(0, len(pcm), 3200):
                await ws.send(pcm[start:start + 3200])
                await asyncio.sleep(0.1)

        sender = asyncio.create_task(send())
        try:
            async with asyncio.timeout(timeout):
                async for frame in ws:
                    if isinstance(frame, bytes):
                        result["frames"]["binary"] += 1
                        result["audio_bytes"] += len(frame)
                        continue
                    result["frames"]["text"] += 1
                    event = json.loads(frame)
                    result["events"].append(event)
                    if event.get("turnComplete"):
                        break
        except websockets.ConnectionClosed as closed:
            result["closed"] = {"code": closed.rcvd.code if closed.rcvd else None,
                                "reason": closed.rcvd.reason if closed.rcvd else None}
        finally:
            sender.cancel()
    return result


def transcript(events, side="outputTranscription") -> str:
    return "".join(e[side].get("text", "") for e in events if side in e and not e.get("partial")).strip()
