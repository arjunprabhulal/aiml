"""Tests for the remote docs server: python -m unittest -v test_remote_auth.py

Each run starts its own token issuer and docs service on free localhost ports.
"""
import asyncio
import json
import os
import time
import unittest
from pathlib import Path
from unittest import mock

import record_flows

HERE = Path(__file__).resolve().parent
METADATA = 'resource_metadata="http://{service}/.well-known/oauth-protected-resource/mcp"'


class RecordedFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flows = record_flows.record()
        cls.editor, cls.reader = (cls.flows["sdk clients"][name] for name in ("docs-editor", "docs-reader"))

    def status(self, label):
        return self.flows[label]["status"]

    def test_a_request_without_a_token_is_told_where_to_get_one(self):
        self.assertEqual(self.status("no token"), 401)
        self.assertIn(METADATA, self.flows["no token"]["www_authenticate"])
        self.assertIn('scope="docs:read"', self.flows["no token"]["www_authenticate"])
        self.assertEqual(self.flows["protected resource metadata"]["body"], {
            "resource": "http://{service}/mcp", "authorization_servers": ["http://{issuer}"],
            "scopes_supported": ["docs:read"], "bearer_methods_supported": ["header"]})

    def test_tokens_are_bound_to_one_resource(self):
        self.assertEqual(self.flows["reader token claims"]["aud"], "http://{service}/mcp")
        self.assertEqual(self.flows["token without resource"]["body"]["error"], "invalid_target")
        self.assertEqual(self.status("token issued for another server"), 401)

    def test_the_issuer_refuses_what_the_client_was_not_given(self):
        self.assertEqual(self.flows["token for a resource the client was not given"]["body"]["error"], "invalid_target")
        self.assertEqual(self.flows["token with a scope the client lacks"]["body"]["error"], "invalid_scope")

    def test_expired_and_query_string_tokens_are_refused(self):
        self.assertEqual((self.status("expired token"), self.status("token in the query string")), (401, 401))

    def test_a_token_without_the_tool_scope_gets_403_insufficient_scope(self):
        for label in ("reader calls publish_page", "Mcp-Name search_docs, body publish_page"):
            self.assertEqual(self.status(label), 403, label)
            self.assertTrue(self.flows[label]["www_authenticate"].startswith('Bearer error="insufficient_scope", scope="docs:write"'))
            self.assertIn(METADATA, self.flows[label]["www_authenticate"])
        self.assertEqual(self.status("reader searches"), 200)

    def test_a_body_that_is_not_one_json_object_is_refused_before_any_tool(self):
        self.assertEqual([self.status(x) for x in ("body that is not JSON", "body with a repeated key", "body over 1 MB")], [400, 400, 413])
        self.assertEqual(self.flows["body with a repeated key"]["body"]["error"]["code"], -32700)

    def test_a_foreign_origin_is_refused(self):
        self.assertEqual((self.status("foreign Origin header"), self.flows["foreign Origin header"]["body"]), (403, "Invalid Origin header"))

    def test_sdk_client_discovers_then_steps_up_to_the_union_of_scopes(self):
        self.assertEqual(self.editor["granted_scope"], "docs:read docs:write")
        self.assertEqual([o["outcome"] for o in self.editor["outcomes"]], ["result", "result", "result"])
        self.assertEqual(self.editor["http"][:4], [
            "POST http://{service}/mcp (server/discover) -> 401",
            "GET http://{service}/.well-known/oauth-protected-resource/mcp -> 200",
            "GET http://{issuer}/.well-known/oauth-authorization-server -> 200",
            "POST http://{issuer}/token -> 200"])
        self.assertIn("POST http://{service}/mcp (tools/call) -> 403", self.editor["http"])

    def test_a_refused_step_up_never_runs_the_tool(self):
        self.assertEqual(self.reader["granted_scope"], "docs:read")
        self.assertIn("invalid_scope", self.reader["outcomes"][-1]["detail"])
        self.assertEqual(self.reader["http"][-1], "POST http://{issuer}/token -> 400")
        self.assertNotIn("publish_page", [o.get("tool") for o in self.reader["outcomes"]])

    def test_a_client_pinned_to_another_issuer_never_sends_its_secret(self):
        pinned = self.flows["sdk client pinned to another issuer"]
        self.assertIn("issuer mismatch", pinned["outcomes"][0]["detail"])
        self.assertFalse(any("/token" in line for line in pinned["http"]))

    def test_saved_fixture_matches_this_run(self):
        self.assertEqual(json.loads((HERE / "auth-flows.json").read_text(encoding="utf-8")), json.loads(json.dumps(self.flows)))


def service_module():
    with mock.patch.dict(os.environ, {"SERVICE_PORT": "1", "ISSUER_URL": "http://127.0.0.1:2"}):
        import docs_service
    return docs_service


def reader_token():
    from mcp.server.auth.provider import AccessToken
    return AccessToken(token="t", client_id="docs-reader", scopes=["docs:read"], expires_at=None)


class ScopeChallengeInProcess(unittest.TestCase):
    """ScopeChallenge in front of a stub app, so a refusal can be checked to stop before the app."""

    def post(self, body):
        service, reached, sent = service_module(), [], []

        async def app(scope, receive, send):
            reached.append((await receive())["body"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": [(b"authorization", b"Bearer t")]}
        with mock.patch.object(service.verifier, "verify_token", mock.AsyncMock(return_value=reader_token())):
            asyncio.run(service.ScopeChallenge(app)(scope, receive, send))
        return sent[0]["status"], json.loads(b"".join(m.get("body", b"") for m in sent[1:])), reached

    def test_a_batch_that_calls_publish_page_is_refused_before_the_app(self):
        batch = [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "publish_page", "arguments": {}}}]
        status, body, reached = self.post(json.dumps(batch).encode())
        self.assertEqual((status, body["error"]["code"], reached), (400, -32600, []))

    def test_a_call_the_token_allows_reaches_the_app_with_the_same_bytes(self):
        call = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search_docs"}}).encode()
        status, _, reached = self.post(call)
        self.assertEqual((status, reached), (200, [call]))


class VerifierClaims(unittest.TestCase):
    """verify_token() with a local signing key, so each claim check is tested on its own."""
    MISSING = object()  # pass as a claim value to leave the claim out of the token

    def setUp(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import ec
        self.jwt, self.service, self.key = jwt, service_module(), ec.generate_private_key(ec.SECP256R1())
        keys = mock.patch.object(self.service.verifier.keys, "get_signing_key_from_jwt", return_value=mock.Mock(key=self.key.public_key()))
        keys.start()
        self.addCleanup(keys.stop)

    def verify(self, **changes):
        now = int(time.time())
        claims = {"iss": "http://127.0.0.1:2", "aud": "http://127.0.0.1:1/mcp", "sub": "docs-reader", "client_id": "docs-reader",
                  "scope": "docs:read", "iat": now, "exp": now + 300, **changes}
        claims = {name: value for name, value in claims.items() if value is not self.MISSING}
        return asyncio.run(self.service.verifier.verify_token(self.jwt.encode(claims, self.key, algorithm="ES256")))

    def test_verify_token_accepts_a_token_for_this_server(self):
        self.assertEqual(self.verify().scopes, ["docs:read"])

    def test_verify_token_refuses_a_token_for_another_audience(self):
        self.assertIsNone(self.verify(aud="http://127.0.0.1:3/mcp"))

    def test_verify_token_refuses_an_expired_token(self):
        self.assertIsNone(self.verify(iat=1, exp=2))

    def test_verify_token_refuses_a_token_without_client_id_or_scope(self):
        """A signed token for this server with a missing or malformed claim is invalid, not a KeyError."""
        for claim in ("client_id", "scope"):
            with self.subTest(missing=claim):
                self.assertIsNone(self.verify(**{claim: self.MISSING}))
        for claim, value in (("client_id", None), ("client_id", 7), ("client_id", ""),
                             ("scope", None), ("scope", ["docs:read"])):
            with self.subTest(malformed=claim, value=value):
                self.assertIsNone(self.verify(**{claim: value}))

class ToolRechecksScope(unittest.TestCase):
    def test_publish_page_refuses_a_token_without_docs_write(self):
        service = service_module()
        from mcp.server.mcpserver.exceptions import ToolError
        with mock.patch.object(service, "get_access_token", return_value=reader_token()):
            with self.assertRaisesRegex(ToolError, "docs:write"):
                service.publish_page("retries", "Retries are off.")


if __name__ == "__main__":
    unittest.main()
