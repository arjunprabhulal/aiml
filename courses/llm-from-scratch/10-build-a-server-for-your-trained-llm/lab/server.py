"""Serve the trained one-block model over HTTP with the standard library.

  GET  /health    -> {"status": "ok", "checkpoint": {"step": ..., "dev_loss": ...}}
  POST /generate  -> {"text": ..., "tokens": [...], "stopped": ..., "settings": {...}}

Run: python3 server.py --port 8000 [--checkpoint best.json]   (listens on 127.0.0.1 only)
One request is handled at a time. There is no authentication, TLS or rate limit:
this is a local teaching server, not a public service.
"""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import checkpoint as ck
import kv_cache as kv
import train as t
from bpe import Tokenizer

HERE = Path(__file__).parent
MAX_BODY_BYTES = 4096
MAX_NEW_TOKENS = 64
FIELDS = {"prompt": str, "max_new_tokens": int, "temperature": (int, float), "top_k": int, "seed": int}


class BadRequest(ValueError):
    pass


def parse_request(body):
    """Validate a /generate body and return keyword arguments for generate_cached()."""
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BadRequest("body must be a JSON object") from None
    if not isinstance(data, dict):
        raise BadRequest("body must be a JSON object")
    unknown = sorted(set(data) - set(FIELDS))
    if unknown:
        raise BadRequest(f"unknown fields: {unknown}")
    if "prompt" not in data:
        raise BadRequest("missing field: prompt")
    for name, kind in FIELDS.items():
        value = data.get(name)
        if name in data and not (name == "top_k" and value is None) and (isinstance(value, bool) or not isinstance(value, kind)):
            raise BadRequest(f"field {name} has the wrong type")
    max_new = data.get("max_new_tokens", MAX_NEW_TOKENS)
    if not 1 <= max_new <= MAX_NEW_TOKENS:
        raise BadRequest(f"max_new_tokens must be from 1 to {MAX_NEW_TOKENS}")
    return {"prompt": data["prompt"], "max_new_tokens": max_new, "temperature": data.get("temperature", 0.0),
            "top_k": data.get("top_k"), "seed": data.get("seed", 0)}


class Service:
    """Loads the verified checkpoint once and answers requests from it."""

    def __init__(self, checkpoint_path=HERE / "best.json"):
        self.tok = Tokenizer.load(HERE / "tokenizer.json")
        best = ck.load(checkpoint_path, t.CONFIG, ck.input_signature(self.tok, (HERE / "corpus.txt").read_text()))
        self.params = best["params"]
        self.checkpoint = {"step": best["step"], "dev_loss": best["dev_loss"]}

    def generate(self, body):
        settings = parse_request(body)
        result = kv.generate_cached(self.params, self.tok, **settings)
        return {"text": result["text"], "tokens": result["steps"], "stopped": result["stopped"],
                "settings": settings, "checkpoint": self.checkpoint}


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                self.send_json(200, {"status": "ok", "checkpoint": service.checkpoint})
            else:
                self.send_json(404, {"error": f"no route {self.path}"})

        def do_POST(self):
            if self.path != "/generate":
                return self.send_json(404, {"error": f"no route {self.path}"})
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self.send_json(411, {"error": "Content-Length is required"})
            if length < 0:
                return self.send_json(400, {"error": "Content-Length must not be negative"})
            if length > MAX_BODY_BYTES:
                return self.send_json(413, {"error": f"body larger than {MAX_BODY_BYTES} bytes"})
            body = self.rfile.read(length)
            try:
                self.send_json(200, service.generate(body))
            except ValueError as error:  # BadRequest and the generator's own checks
                self.send_json(400, {"error": str(error)})

        def log_message(self, *args):  # keep test output quiet; a real service would log requests
            pass

    return Handler


def make_server(port=0, service=None):
    """Create the server bound to 127.0.0.1 only; both start() and the command line use it."""
    return HTTPServer(("127.0.0.1", port), make_handler(service or Service()))


def start(port=0, service=None):
    """Start the server on 127.0.0.1 in a background thread and return it."""
    server = make_server(port, service)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--checkpoint", default=str(HERE / "best.json"))
    args = parser.parse_args()
    server = make_server(args.port, Service(Path(args.checkpoint)))
    host, port = server.server_address
    print(f"serving on http://{host}:{port}", flush=True)
    server.serve_forever()
