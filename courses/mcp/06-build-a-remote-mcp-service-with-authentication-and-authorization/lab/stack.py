"""Start the token issuer and the docs service on free localhost ports, with client secrets made at run time.

Use as a context manager: `with Stack() as stack: ...`. Both processes stop on exit.
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_for(url, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"{url} did not start")


class Stack:
    def __init__(self):
        self.issuer_port, self.service_port, other_port = free_port(), free_port(), free_port()
        self.issuer = f"http://127.0.0.1:{self.issuer_port}"
        self.resource = f"http://127.0.0.1:{self.service_port}/mcp"
        self.other_resource = f"http://127.0.0.1:{other_port}/mcp"  # some other server's URI
        self.clients = {
            "docs-reader": {"secret": secrets.token_urlsafe(16), "scopes": ["docs:read"],
                            "resources": [self.resource, self.other_resource]},
            "docs-editor": {"secret": secrets.token_urlsafe(16), "scopes": ["docs:read", "docs:write"],
                            "resources": [self.resource]},
            "short-lived": {"secret": secrets.token_urlsafe(16), "scopes": ["docs:read"],
                            "resources": [self.resource], "lifetime": 1},
        }
        self.processes = []

    def __enter__(self):
        issuer_env = {**os.environ, "ISSUER_PORT": str(self.issuer_port), "CLIENTS_JSON": json.dumps(self.clients)}
        service_env = {**os.environ, "SERVICE_PORT": str(self.service_port), "ISSUER_URL": self.issuer}  # no client secrets
        try:
            for script, env, ready in (
                    ("token_issuer.py", issuer_env, f"{self.issuer}/jwks.json"),
                    ("docs_service.py", service_env, f"http://127.0.0.1:{self.service_port}/.well-known/oauth-protected-resource/mcp")):
                self.processes.append(subprocess.Popen([sys.executable, str(HERE / script)], env=env,
                                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                wait_for(ready)
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        for process in reversed(self.processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self.processes = []
