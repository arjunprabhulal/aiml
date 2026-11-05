"""Record the HTTP requests and responses the SDK client sends to serve.py --http. Run: python wire.py

The SDK's own Streamable HTTP transport makes every request; an httpx event hook only records them.
Writes wire-exchange.json.
"""
import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

HERE = Path(__file__).resolve().parent
SHOWN_HEADERS = ("accept", "content-type", "mcp-protocol-version", "mcp-method", "mcp-name")


async def record_calls(url: str) -> list[dict]:
    exchange = []

    async def on_response(response: httpx2.Response) -> None:
        await response.aread()
        request = response.request
        exchange.append({
            "request": {"method": request.method, "path": request.url.path,
                        "headers": {k: v for k, v in request.headers.items() if k in SHOWN_HEADERS},
                        "body": json.loads(request.content)},
            "response": {"status": response.status_code, "contentType": response.headers["content-type"],
                         "body": json.loads(response.content)},
        })

    async with httpx2.AsyncClient(event_hooks={"response": [on_response]}) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            await client.call_tool("complete_task", {"task_id": "T-1"})
            await client.call_tool("complete_task", {"task_id": "T-9"})
    return exchange


def collect() -> list[dict]:
    """Start serve.py --http on a free port, make two calls and return every HTTP exchange."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, "serve.py", "--http", "--port", str(port)], cwd=HERE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while socket.socket().connect_ex(("127.0.0.1", port)) != 0:
            time.sleep(0.1)
        return asyncio.run(record_calls(f"http://127.0.0.1:{port}/mcp"))
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    (HERE / "wire-exchange.json").write_text(json.dumps(collect(), indent=2) + "\n", encoding="utf-8")
