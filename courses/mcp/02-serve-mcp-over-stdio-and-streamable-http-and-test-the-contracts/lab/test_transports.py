"""Integration tests: the same server over stdio and over Streamable HTTP. Run: python -m pytest -v"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters
from mcp.shared.exceptions import MCPError

import wire

pytestmark = pytest.mark.anyio
HERE = Path(__file__).resolve().parent
STDIO = StdioServerParameters(command=sys.executable, args=[str(HERE / "serve.py")])


@pytest.fixture
def anyio_backend():
    return "asyncio"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def http_url():
    """Start serve.py --http on a free port and return its MCP endpoint."""
    port = free_port()
    process = subprocess.Popen([sys.executable, "serve.py", "--http", "--port", str(port)], cwd=HERE, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 15
    while socket.socket().connect_ex(("127.0.0.1", port)) != 0:
        assert time.monotonic() < deadline and process.poll() is None, "server did not start"
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}/mcp"
    process.terminate()
    process.wait(timeout=10)


async def round_trip(target) -> tuple:
    async with Client(target) as client:
        names = [tool.name for tool in (await client.list_tools()).tools]
        added = await client.call_tool("add_task", {"title": "Tag v1.2"})
        return names, added.structured_content["id"]


async def test_stdio_round_trip():
    assert await round_trip(STDIO) == (["list_tasks", "add_task", "complete_task"], "T-4")


async def test_streamable_http_round_trip(http_url):
    assert await round_trip(http_url) == (["list_tasks", "add_task", "complete_task"], "T-4")


async def test_http_clients_share_one_server_process(http_url):
    assert (await round_trip(http_url))[1] == "T-4"
    assert (await round_trip(http_url))[1] == "T-5"
    assert (await round_trip(STDIO))[1] == "T-4"  # each stdio client starts its own process


async def test_print_to_stdout_corrupts_the_stdio_stream(caplog):
    noisy = StdioServerParameters(command=sys.executable, cwd=str(HERE), args=[
        "-c", "print('tasks server starting'); import runpy; runpy.run_path('serve.py', run_name='__main__')"])
    assert (await round_trip(noisy))[0] == ["list_tasks", "add_task", "complete_task"]
    assert "Failed to parse JSONRPC message from server" in caplog.text


async def test_wrong_endpoint_path_is_not_found(http_url):
    with pytest.raises(ExceptionGroup) as raised:
        await round_trip(http_url.replace("/mcp", "/tasks"))
    assert raised.group_contains(MCPError, match="Not Found")


def test_foreign_host_header_is_rejected(http_url):
    request = urllib.request.Request(http_url, method="POST", data=b"{}", headers={
        "Host": "tasks.example.com", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    with pytest.raises(urllib.error.HTTPError) as raised:
        urllib.request.urlopen(request, timeout=10)
    assert (raised.value.code, raised.value.read()) == (421, b"Invalid Host header")


def test_client_script_prints_the_recorded_output(http_url):
    runs = [["stdio"], [http_url], [http_url]]
    printed = "".join(subprocess.run([sys.executable, "client.py", *arg], cwd=HERE, capture_output=True, text=True,
                                     timeout=60, check=True).stdout for arg in runs)
    assert printed == (HERE / "client-output.txt").read_text(encoding="utf-8")


def test_server_is_the_typed_tools_lesson_server():
    assert (HERE / "tasks_server.py").read_bytes() == (HERE.parent / "mcp-typed-tools" / "tasks_server.py").read_bytes()


def test_recorded_http_exchange_matches_a_fresh_run():
    assert wire.collect() == json.loads((HERE / "wire-exchange.json").read_text(encoding="utf-8"))
