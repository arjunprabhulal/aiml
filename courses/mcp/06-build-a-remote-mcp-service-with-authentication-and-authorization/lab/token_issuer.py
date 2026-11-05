"""A test token issuer for this lesson. It is NOT a full OAuth 2.1 authorization server.

Usage: ISSUER_PORT=9001 CLIENTS_JSON='{...}' python token_issuer.py

It serves authorization server metadata (RFC 8414), a JSON Web Key Set and a token
endpoint for the client_credentials grant only. Every token is a JWT signed with an
ES256 key made at start-up and bound to the `resource` the client names (RFC 8707).
There is no user sign-in, consent, authorization code or PKCE.
"""
import json
import os
import secrets
import time

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import ec
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

PORT = int(os.environ["ISSUER_PORT"])
ISSUER = f"http://127.0.0.1:{PORT}"
CLIENTS = json.loads(os.environ["CLIENTS_JSON"])  # {client_id: {"secret", "scopes", "resources", "lifetime"?}}
KEY = ec.generate_private_key(ec.SECP256R1())
KID = secrets.token_hex(8)
PUBLIC_JWK = {**json.loads(jwt.algorithms.ECAlgorithm.to_jwk(KEY.public_key())), "kid": KID, "use": "sig", "alg": "ES256"}


def oauth_error(status, error, description):
    return JSONResponse({"error": error, "error_description": description}, status_code=status)


async def metadata(request):
    return JSONResponse({
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",  # mcp 2.3.0's metadata model requires it; it only refuses
        "response_types_supported": [],
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks.json",
        "grant_types_supported": ["client_credentials"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "scopes_supported": ["docs:read", "docs:write"],
    })


async def authorize(request):
    return oauth_error(400, "unsupported_response_type", "this test issuer has no user sign-in; use the token endpoint")


async def jwks(request):
    return JSONResponse({"keys": [PUBLIC_JWK]})


async def token(request):
    form = await request.form()
    client = CLIENTS.get(form.get("client_id", ""))
    if form.get("grant_type") != "client_credentials":
        return oauth_error(400, "unsupported_grant_type", "only client_credentials is supported")
    if client is None or not secrets.compare_digest(client["secret"], form.get("client_secret", "")):
        return oauth_error(401, "invalid_client", "unknown client or wrong secret")
    if form.get("resource") not in client["resources"]:
        return oauth_error(400, "invalid_target", "the resource is missing or not allowed for this client")
    scopes = form.get("scope", "").split()
    if not scopes or not set(scopes) <= set(client["scopes"]):
        return oauth_error(400, "invalid_scope", "a requested scope is not allowed for this client")
    now, lifetime = int(time.time()), client.get("lifetime", 300)
    claims = {"iss": ISSUER, "sub": form["client_id"], "client_id": form["client_id"], "aud": form["resource"],
              "scope": " ".join(scopes), "iat": now, "exp": now + lifetime, "jti": secrets.token_hex(8)}
    return JSONResponse({"access_token": jwt.encode(claims, KEY, algorithm="ES256", headers={"kid": KID}),
                         "token_type": "Bearer", "expires_in": lifetime, "scope": " ".join(scopes)})


app = Starlette(routes=[Route("/.well-known/oauth-authorization-server", metadata), Route("/authorize", authorize),
                        Route("/jwks.json", jwks), Route("/token", token, methods=["POST"])])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
