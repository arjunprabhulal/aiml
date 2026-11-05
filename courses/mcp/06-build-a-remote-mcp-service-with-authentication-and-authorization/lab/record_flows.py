"""Send every request in the lesson to a local issuer and docs service, and save what came back.

Usage: python record_flows.py [--write auth-flows.json]
Ports and tokens differ on every run; the saved file replaces them with {issuer}, {service} and {other}.
"""
import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

import httpx2
import jwt

from client import run_client
from stack import Stack

logging.getLogger("mcp.client.auth").setLevel(logging.CRITICAL)  # the client's outcome list records the same error
META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "MCP-Protocol-Version": "2026-07-28"}
PUBLISH = {"name": "publish_page", "arguments": {"slug": "retries", "text": "Retries are off."}}
SEARCH = {"name": "search_docs", "arguments": {"query": "worker"}}


def rpc(method, params=None):
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": {**(params or {}), "_meta": META}}


class Recorder:
    def __init__(self, stack):
        self.stack, self.http, self.results = stack, httpx2.Client(timeout=10), {}

    def clean(self, text):
        other = self.stack.other_resource.split("//")[1].split("/")[0]
        return (text.replace(f"127.0.0.1:{self.stack.service_port}", "{service}")
                    .replace(f"127.0.0.1:{self.stack.issuer_port}", "{issuer}").replace(other, "{other}"))

    def keep(self, label, response):
        try:
            body = json.loads(self.clean(response.text))
        except ValueError:
            body = self.clean(response.text)
        self.results[label] = {"status": response.status_code, "body": body,
                               "www_authenticate": self.clean(response.headers.get("www-authenticate", "")) or None}

    def token(self, client, scope, resource):
        return self.http.post(f"{self.stack.issuer}/token", data={
            "grant_type": "client_credentials", "client_id": client, "client_secret": self.stack.clients[client]["secret"],
            "scope": scope, "resource": resource})

    def mcp(self, label, message, token=None, **extra):
        headers = {**HEADERS, "Mcp-Method": message["method"], **extra}
        if message["method"] == "tools/call":
            headers.setdefault("Mcp-Name", message["params"]["name"])
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.keep(label, self.http.post(self.stack.resource, json=message, headers=headers))


def raw_flows(rec):
    s = rec.stack
    rec.mcp("no token", rpc("tools/list"))
    rec.keep("protected resource metadata", rec.http.get(f"http://127.0.0.1:{s.service_port}/.well-known/oauth-protected-resource/mcp"))
    rec.keep("authorization server metadata", rec.http.get(f"{s.issuer}/.well-known/oauth-authorization-server"))
    rec.keep("token without resource", rec.token("docs-reader", "docs:read", ""))
    rec.keep("token with a scope the client lacks", rec.token("docs-reader", "docs:write", s.resource))
    rec.keep("token for a resource the client was not given", rec.token("docs-editor", "docs:read", s.other_resource))
    reader = rec.token("docs-reader", "docs:read", s.resource).json()["access_token"]
    rec.results["reader token claims"] = {k: rec.clean(str(v)) for k, v in jwt.decode(reader, options={"verify_signature": False}).items()
                                          if k in ("iss", "aud", "sub", "scope")}
    rec.mcp("reader searches", rpc("tools/call", SEARCH), reader)
    rec.mcp("reader calls publish_page", rpc("tools/call", PUBLISH), reader)
    rec.mcp("Mcp-Name search_docs, body publish_page", rpc("tools/call", PUBLISH), reader, **{"Mcp-Name": "search_docs"})
    raw = {**HEADERS, "Mcp-Method": "tools/call", "Authorization": f"Bearer {reader}"}
    rec.keep("body that is not JSON", rec.http.post(s.resource, content=b"tools/call publish_page", headers=raw))
    repeated = b'{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search_docs", "name": "publish_page"}}'
    rec.keep("body with a repeated key", rec.http.post(s.resource, content=repeated, headers=raw))
    rec.keep("body over 1 MB", rec.http.post(s.resource, content=b" " * 1_000_001, headers=raw))
    rec.mcp("foreign Origin header", rpc("tools/list"), reader, Origin="http://attacker.example")
    other = rec.token("docs-reader", "docs:read", s.other_resource).json()["access_token"]
    rec.mcp("token issued for another server", rpc("tools/list"), other)
    short = rec.token("short-lived", "docs:read", s.resource).json()["access_token"]
    time.sleep(2)
    rec.mcp("expired token", rpc("tools/list"), short)
    rec.keep("token in the query string", rec.http.post(f"{s.resource}?access_token={reader}", json=rpc("tools/list"),
                                                       headers={**HEADERS, "Mcp-Method": "tools/list"}))
    rec.results["reader searches"]["body"]["result"].pop("_meta", None)


CALLS = [("search_docs", {"query": "worker"}), ("publish_page", {"slug": "retries", "text": "Retries are off."}),
         ("search_docs", {"query": "retries"})]


async def sdk_flows(rec):
    """The same three calls from two OAuth clients: one allowed docs:write, one not."""
    rec.results["sdk clients"] = {c: await run_client(rec.stack, c, CALLS, rec.clean) for c in ("docs-editor", "docs-reader")}
    elsewhere = "http://" + rec.stack.other_resource.split("//")[1].split("/")[0]  # not the issuer the server names
    rec.results["sdk client pinned to another issuer"] = await run_client(rec.stack, "docs-editor", CALLS[:1], rec.clean, elsewhere)


def record():
    with Stack() as stack:
        rec = Recorder(stack)
        with rec.http:
            raw_flows(rec)
            asyncio.run(sdk_flows(rec))
        return rec.results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=Path)
    results = record()
    for label, value in results.items():
        if "status" in value:
            print(f"{label:46} {value['status']}")
    clients = [*results["sdk clients"].values(), {**results["sdk client pinned to another issuer"], "note": " pinned to another issuer"}]
    for client in clients:
        print(f"SDK client {client['client']}{client.get('note', '')}: granted {client['granted_scope']!r}")
        for outcome in client["outcomes"]:
            print(f"  {outcome.get('tool', '-'):14} {outcome['outcome']}")
        for line in client["http"]:
            print(f"    {line}")
    if (path := parser.parse_args(argv).write):
        path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
