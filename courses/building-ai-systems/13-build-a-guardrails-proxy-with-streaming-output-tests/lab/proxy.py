"""A guardrails proxy that streams a model's answer to the client through StreamGuard.

    python3 proxy.py --upstream replay   # serve recorded streams (default)
    python3 proxy.py --upstream ollama   # forward to a local Ollama server

POST /api/chat with an Ollama chat request and "stream": true. The proxy reads the
upstream stream chunk by chunk, sends the client only what the guard releases, as
newline-delimited JSON like Ollama's, and ends with one line that has "done": true,
the done_reason ("guardrail" when the guard blocked) and the guard's findings. When
the guard blocks, the proxy stops reading the upstream stream. Standard library only.
"""
import argparse
import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest

import guard

HERE = Path(__file__).resolve().parent
MODEL = json.loads((HERE / "model.json").read_text(encoding="utf-8"))
RECORDING = HERE / "recorded" / "streams.json"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request_sha256(payload):
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


class OllamaUpstream:
    """Yields (content, final) for each line of a live Ollama stream, and records it."""

    def __init__(self, base_url="http://127.0.0.1:11434"):
        self.base_url, self.recorded = base_url, {}
        with urlrequest.urlopen(base_url + "/api/tags", timeout=30) as response:
            installed = {m["name"]: m["digest"] for m in json.load(response)["models"]}
        if installed.get(MODEL["ollama_tag"]) != MODEL["ollama_digest"]:
            raise RuntimeError(f"{MODEL['ollama_tag']} is missing or not the pinned digest")

    def stream(self, payload):
        req = urlrequest.Request(self.base_url + "/api/chat", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
        chunks = []
        with urlrequest.urlopen(req, timeout=600) as response:
            for line in response:
                event = json.loads(line)
                chunks.append(event["message"]["content"])
                if event.get("done"):
                    final = {k: event.get(k) for k in ("done_reason", "prompt_eval_count", "eval_count")}
                    self.recorded[request_sha256(payload)] = {"chunks": chunks, "final": final}
                    yield chunks[-1], final
                    return
                yield chunks[-1], None


class ReplayUpstream:
    """Yields the recorded chunks of the stream that answered this exact request."""

    def __init__(self, path=RECORDING):
        recording = json.loads(Path(path).read_text(encoding="utf-8"))
        if recording["model"] != MODEL:
            raise RuntimeError("recording was made with a different model pin")
        self.streams, self.read = recording["streams"], []

    def stream(self, payload):
        try:
            recorded = self.streams[request_sha256(payload)]
        except KeyError:
            raise LookupError("no recorded stream for this exact request") from None
        for i, chunk in enumerate(recorded["chunks"]):
            self.read.append(i)  # how far the proxy read: it stops early after a block
            yield chunk, recorded["final"] if i == len(recorded["chunks"]) - 1 else None


def make_handler(upstream, action):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            check, final = guard.StreamGuard(action), None
            for content, final in upstream.stream(payload):
                released = check.feed(content)
                if released:
                    self.send_line({"message": {"role": "assistant", "content": released}, "done": False})
                if check.blocked:
                    break  # stop reading the model's stream
            rest = check.finish()
            if rest:
                self.send_line({"message": {"role": "assistant", "content": rest}, "done": False})
            reason = "guardrail" if check.blocked else (final or {}).get("done_reason")
            self.send_line({"done": True, "done_reason": reason,
                            "guardrail": {"action": action, "findings": check.findings, "max_held": check.max_held}})

        def send_line(self, event):
            self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        def log_message(self, *args):
            pass

    return Handler


def serve(upstream, action="redact"):
    """Start the proxy on a port the operating system chooses; return the server."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(upstream, action))
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upstream", choices=["replay", "ollama"], default="replay")
    parser.add_argument("--action", choices=["redact", "block"], default="redact")
    options = parser.parse_args(argv)
    upstream = ReplayUpstream() if options.upstream == "replay" else OllamaUpstream()
    server = serve(upstream, options.action)
    print(f"listening on http://127.0.0.1:{server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
