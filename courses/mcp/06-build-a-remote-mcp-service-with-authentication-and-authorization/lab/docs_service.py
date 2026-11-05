"""A remote docs server over Streamable HTTP that accepts only access tokens issued for it.

Usage: SERVICE_PORT=9002 ISSUER_URL=http://127.0.0.1:9001 python docs_service.py

The server is an OAuth 2.1 resource server. It publishes Protected Resource Metadata
(RFC 9728), checks each bearer token's signature, issuer, audience and expiry, needs
docs:read for any MCP request and docs:write for publish_page. It listens on
127.0.0.1 only and refuses a Host or Origin header that is not its own.
"""
import json
import os
from typing import TypedDict

import jwt
import uvicorn
from starlette.responses import JSONResponse

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

PORT = int(os.environ["SERVICE_PORT"])
ISSUER_URL = os.environ["ISSUER_URL"]
RESOURCE = f"http://127.0.0.1:{PORT}/mcp"  # the canonical server URI; tokens must name it as their audience
METADATA_URL = f"http://127.0.0.1:{PORT}/.well-known/oauth-protected-resource/mcp"
TOOL_SCOPES = {"publish_page": "docs:write"}  # extra scope per tool; docs:read is needed for everything
MAX_BODY_BYTES = 1_000_000
PAGES = {"quickstart": "Start a worker with taskq worker emails.", "retries": "A failed job is retried 3 times."}


class JwtVerifier:
    """Verify ES256 JWTs from the issuer's key set; refuse any token not issued for this server."""

    def __init__(self, issuer, audience):
        self.issuer, self.audience = issuer, audience
        self.keys = jwt.PyJWKClient(f"{issuer}/jwks.json")

    async def verify_token(self, token):
        try:
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["ES256"], audience=self.audience, issuer=self.issuer,
                                options={"require": ["exp", "iat", "aud", "iss", "sub", "client_id", "scope"]})
        except jwt.PyJWTError:
            return None
        # A signed token can still carry a claim of the wrong type: treat it as invalid, not as a crash.
        if not (isinstance(claims["client_id"], str) and claims["client_id"] and isinstance(claims["scope"], str)):
            return None
        return AccessToken(token=token, client_id=claims["client_id"], scopes=claims["scope"].split(),
                           expires_at=claims["exp"], resource=claims["aud"], subject=claims["sub"])


verifier = JwtVerifier(ISSUER_URL, RESOURCE)
server = MCPServer("docs", version="1.0.0", token_verifier=verifier,
                   auth=AuthSettings(issuer_url=ISSUER_URL, resource_server_url=RESOURCE,
                                     required_scopes=["docs:read"], validate_token_resource=True))


class Page(TypedDict):
    slug: str
    text: str
    caller: str  # the client_id from the token, so each answer shows who asked


@server.tool()
def search_docs(query: str) -> list[Page]:
    """Return the docs pages that contain the query. Needs docs:read."""
    caller = get_access_token().client_id
    return [{"slug": s, "text": t, "caller": caller} for s, t in PAGES.items() if query.lower() in t.lower()]


@server.tool()
def publish_page(slug: str, text: str) -> Page:
    """Create or replace one docs page. Needs docs:write."""
    token = get_access_token()
    if "docs:write" not in token.scopes:  # second check: never rely on the HTTP layer alone
        raise ToolError("The token lacks docs:write.")
    PAGES[slug] = text
    return {"slug": slug, "text": text, "caller": token.client_id}


def refuse_duplicate_keys(pairs):
    if len({key for key, _ in pairs}) != len(pairs):  # two parsers could keep different copies of a repeated key
        raise ValueError("duplicate key")
    return dict(pairs)


async def read_body(receive):
    """The whole request body, or None once it passes MAX_BODY_BYTES."""
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if message["type"] == "http.disconnect" or len(body) > MAX_BODY_BYTES:
            return None
        if not message.get("more_body"):
            return body


def rpc_error(code, text):
    return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": text}}, status_code=400)


def check(body, token):
    """A refusal for this request body, or None to let the SDK run it."""
    if body is None:
        return JSONResponse({"error": "request body too large"}, status_code=413)
    try:
        message = json.loads(body, object_pairs_hook=refuse_duplicate_keys)
    except (ValueError, RecursionError):  # not JSON, not UTF-8, or a repeated key
        return rpc_error(-32700, "Parse error")
    if not isinstance(message, dict):  # a batch or a bare value: the SDK runs neither
        return rpc_error(-32600, "Invalid Request")
    needed = tool_scope(message)
    if needed and needed not in token.scopes:
        challenge = (f'Bearer error="insufficient_scope", scope="{needed}", '
                     f'resource_metadata="{METADATA_URL}", error_description="This tool needs {needed}"')
        return JSONResponse({"error": "insufficient_scope", "error_description": f"This tool needs {needed}"},
                            status_code=403, headers={"WWW-Authenticate": challenge})
    return None


class ScopeChallenge:
    """ASGI middleware: answer 403 insufficient_scope before a tool runs when the token lacks that tool's scope.

    The tool name comes from the JSON-RPC body, the same bytes the SDK runs, never from the
    Mcp-Name header. Compliant modern calls must include a matching header; malformed clients can omit it.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST":
            auth = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"authorization"), "")  # the first, as Starlette reads it
            token = await verifier.verify_token(auth[7:]) if auth.lower().startswith("bearer ") else None
            if token is not None:  # without a valid token the SDK answers 401 and the body is never read
                body = await read_body(receive)
                if (response := check(body, token)) is not None:
                    return await response(scope, receive, send)
                receive = replay(body, receive)

        async def add_scope_to_401(message):
            # The SDK's 401 names the metadata URL; the authorization spec also asks for the scope.
            if message["type"] == "http.response.start" and message["status"] == 401:
                message = {**message, "headers": [(k, v + b', scope="docs:read"') if k == b"www-authenticate" else (k, v)
                                                  for k, v in message["headers"]]}
            await send(message)

        await self.app(scope, receive, add_scope_to_401)


def tool_scope(message):
    """The extra scope a tools/call message needs, read from params.name."""
    params = message.get("params")
    if message.get("method") == "tools/call" and isinstance(params, dict) and isinstance(params.get("name"), str):
        return TOOL_SCOPES.get(params["name"])
    return None


def replay(body, receive):
    """A receive() that gives the app the body this middleware already read, then the real stream."""
    sent = False

    async def again():
        nonlocal sent
        if sent:
            return await receive()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}
    return again


app = ScopeChallenge(server.streamable_http_app(json_response=True, transport_security=TransportSecuritySettings(
    enable_dns_rebinding_protection=True, allowed_hosts=[f"127.0.0.1:{PORT}"], allowed_origins=[f"http://127.0.0.1:{PORT}"])))

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
