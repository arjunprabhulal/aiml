"""Call the remote docs server as an OAuth client with the MCP SDK's client_credentials provider.

The client starts with no token and no scope. The server's 401 names its Protected Resource
Metadata; the SDK reads it, finds the authorization server and asks for a token for this
server with the scope the challenge named. A later 403 insufficient_scope makes the SDK ask
again for the union of the old and new scopes. Every HTTP request it sends is recorded.
"""
from mcp import Client, MCPError
from mcp.client.auth import OAuthFlowError, OAuthTokenError
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

AUTH_ERRORS = (OAuthFlowError, OAuthTokenError)


class MemoryTokenStorage:
    """Tokens in memory only. A real client keeps them in a secret store, never in logs."""

    tokens = client_info = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, client_info):
        self.client_info = client_info


async def run_client(stack, client_id, calls, clean=str, issuer=None):
    """Make `calls` [(tool, arguments)] as `client_id`; return each outcome and the HTTP requests sent.

    `issuer` is the only authorization server the client sends its secret to; it defaults to the stack's issuer.
    """
    sent, outcomes, storage = [], [], MemoryTokenStorage()

    async def record(response):
        method = response.request.headers.get("mcp-method")
        target = clean(f"{response.request.method} {response.request.url.copy_with(query=None)}")
        sent.append(f"{target}{f' ({method})' if method else ''} -> {response.status_code}")

    auth = ClientCredentialsOAuthProvider(
        server_url=stack.resource, storage=storage, client_id=client_id, client_secret=stack.clients[client_id]["secret"],
        token_endpoint_auth_method="client_secret_post", issuer=issuer or stack.issuer)
    http = create_mcp_http_client(auth=auth)
    http.event_hooks["response"].append(record)
    try:
        async with http, Client(streamable_http_client(stack.resource, http_client=http)) as client:
            for tool, arguments in calls:
                try:
                    result = await client.call_tool(tool, arguments)
                    outcomes.append({"tool": tool, "outcome": "tool_error" if result.is_error else "result"})
                except MCPError as error:
                    outcomes.append({"tool": tool, "outcome": "protocol_error", "detail": error.error.message})
    except BaseException as error:  # anyio wraps errors raised inside the transport's task group
        found = [e for e in getattr(error, "exceptions", [error]) if isinstance(e, AUTH_ERRORS)]
        if not found:
            raise
        outcomes.append({"outcome": "authorization_failed", "detail": clean(f"{type(found[0]).__name__}: {found[0]}")})
    return {"client": client_id, "granted_scope": storage.tokens.scope if storage.tokens else None,
            "outcomes": outcomes, "http": sent}
