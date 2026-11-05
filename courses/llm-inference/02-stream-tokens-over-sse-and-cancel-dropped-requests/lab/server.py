"""Bounded loopback SSE server with explicit cancellation and a real local-model adapter."""

from __future__ import annotations
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def handler_for(backend, capacity=1):
    slots = threading.BoundedSemaphore(capacity)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/generate":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    raise ValueError("Expected a bounded JSON body")
                body = json.loads(self.rfile.read(size))
                prompt = body["prompt"]
                limit = body.get("max_new_tokens", 24)
                if not isinstance(prompt, str) or not prompt.strip():
                    raise ValueError("Prompt must not be empty")
                if not isinstance(limit, int) or not 1 <= limit <= 256:
                    raise ValueError("Output limit must be between 1 and 256")
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
                return
            if not slots.acquire(blocking=False):
                self.send_error(429)
                return
            stream = None
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                stream = backend.stream(prompt, limit)
                for token in stream:
                    frame = (
                        "data: "
                        + json.dumps({"token": token}, ensure_ascii=False)
                        + "\n\n"
                    )
                    self.wfile.write(frame.encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Detects failed writes. A silent peer may require socket timeout/heartbeat in a deployed adapter.
                pass
            finally:
                if stream is not None:
                    stream.close()
                slots.release()
                self.close_connection = True

    return Handler


class ModelBackend:
    def __init__(self, model_path, device):
        from live_inference import LocalDecoder

        self.decoder = LocalDecoder(model_path, device)

    def stream(self, prompt, limit):
        d = self.decoder
        cache = None
        result = None
        try:
            ids = d.encode(prompt)
            result = d._forward(ids)
            cache = result.past_key_values
            eos = d.model.generation_config.eos_token_id
            eos = set(eos if isinstance(eos, list) else [eos])
            emitted = []
            previous = ""
            for step in range(limit):
                token = result.logits[:, -1].argmax(-1, keepdim=True)
                d.sync()
                token_id = int(token.item())
                emitted.append(token_id)
                text = d.tokenizer.decode(emitted, skip_special_tokens=True)
                if not text.endswith("\ufffd") and text.startswith(previous):
                    piece = text[len(previous) :]
                    previous = text
                    if piece:
                        yield piece
                if token_id in eos or step + 1 == limit:
                    break
                result = d._forward(token, cache)
                cache = result.past_key_values
        finally:
            del cache, result
            d.sync()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model-path", required=True)
    p.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    p.add_argument("--port", type=int, default=8766)
    a = p.parse_args()
    server = ThreadingHTTPServer(
        ("127.0.0.1", a.port), handler_for(ModelBackend(a.model_path, a.device))
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
