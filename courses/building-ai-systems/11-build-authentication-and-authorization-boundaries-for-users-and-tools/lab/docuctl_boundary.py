"""The gateway and two tool services, with the authorization boundary between users, the agent and tools.

The model proposes tool calls. The gateway decides whether the signed-in user may
make each one, and the tool service decides again with its own checks:

  gateway   verify the user's session token; refuse an unknown tool or arguments that
            break the tool's schema; refuse a tool whose scope the user's role does not
            grant (deny by default); otherwise mint a delegated token for this one call:
            the user as sub, the user's tenant, only this tool's scope, the agent as
            act, this tool's service as aud, a short expiry and a fresh jti
  service   verify that token for its own audience and type, once; require the act
            claim and the tool's scope; read the object only within the token's tenant

The session token never leaves the gateway. Every decision is written to an audit
log with the reason, and with no token in it. Standard library only.
"""
import hashlib
import json
from pathlib import Path

import tokens

HERE = Path(__file__).resolve().parent
POLICY = json.loads((HERE / "docuctl_policy.json").read_text(encoding="utf-8"))


class Refused(Exception):
    """A call stopped at a check. status is the HTTP-style code, check names the check."""

    def __init__(self, status, check, reason):
        super().__init__(reason)
        self.status, self.check, self.reason = status, check, reason


def schema_problem(arguments, schema):
    if not isinstance(arguments, dict):
        return "arguments must be an object"
    for name in schema["required"]:
        if name not in arguments:
            return f"missing required argument {name}"
    extra = sorted(set(arguments) - set(schema["properties"]))
    if extra and schema.get("additionalProperties") is False:
        return f"unexpected argument {', '.join(extra)}"
    for name, value in arguments.items():
        rule = schema["properties"].get(name, {})
        if rule.get("type") == "string" and not isinstance(value, str):
            return f"{name} must be a string"
        if "enum" in rule and value not in rule["enum"]:
            return f"{name} must be one of {', '.join(rule['enum'])}"
    return None


class ToolService:
    """One downstream service. It trusts no caller: it checks the token it receives itself."""

    def __init__(self, name, clock):
        self.name, self.clock, self.seen_jti = name, clock, set()

    def handle(self, token, tool, arguments):
        try:
            claims = tokens.verify(token, audience=self.name, typ="tool+jwt", now=self.clock(), seen_jti=self.seen_jti)
        except (tokens.TokenError, TypeError) as error:
            raise Refused(401, "service token", str(error)) from None
        rule = POLICY["tools"].get(tool) if isinstance(tool, str) else None
        if rule is None:
            raise Refused(404, "service tool", "unknown tool")
        problem = schema_problem(arguments, rule["input_schema"])
        if problem:
            raise Refused(400, "schema", problem)
        if rule["service"] != self.name:
            raise Refused(404, "service tool", f"{self.name} has no tool {tool}")
        actor = claims.get("act")
        if not isinstance(actor, dict) or actor.get("sub") != POLICY["agent"]:
            raise Refused(403, "service delegation", "an agent call must carry the act claim")
        if not isinstance(claims.get("scope"), str) or rule["scope"] not in claims["scope"].split():
            raise Refused(403, "service scope", f"token lacks {rule['scope']}")
        if any(not isinstance(claims.get(k), str) or not claims[k] for k in ("sub", "tenant")):
            raise Refused(403, "service identity", "missing or invalid user identity")
        page = POLICY["pages"].get(arguments["page_id"])
        if page is None or page["tenant"] != claims["tenant"]:
            raise Refused(404, "service tenant", "page not found")  # same reply as a missing page
        if tool == "read_page":
            return {"page_id": arguments["page_id"], "status": page["status"]}
        return {"page_id": arguments["page_id"], "published": True, "reason": arguments["reason"]}


class Gateway:
    def __init__(self, clock, services):
        self.clock, self.services, self.audit, self.minted = clock, services, [], 0

    def log(self, user, call, decision, check, reason, jti=None):
        self.audit.append({"at": self.clock(), "user": user, "tool": call.get("name"),
                           "arguments_sha256": hashlib.sha256(json.dumps(call.get("arguments"), sort_keys=True)
                                                              .encode()).hexdigest(),
                           "decision": decision, "check": check, "reason": reason, "jti": jti})

    def delegate(self, user, rule):
        """A token for exactly one call: this user, this tenant, this tool's scope and service."""
        self.minted += 1
        jti = hashlib.sha256(f"{user['sub']}:{self.clock()}:{self.minted}".encode()).hexdigest()[:16]
        claims = {"sub": user["sub"], "tenant": user["tenant"], "scope": rule["scope"],
                  "act": {"sub": POLICY["agent"]}, "aud": rule["service"],
                  "exp": self.clock() + POLICY["delegated_token_seconds"], "jti": jti}
        return tokens.sign(claims, typ="tool+jwt"), jti

    def call_tool(self, session_token, call):
        """Run one proposed tool call for the signed-in user. Return (status, result)."""
        if not isinstance(call, dict):
            self.log(None, {}, "refused", "schema", "call must be an object")
            return 400, {"error": "call must be an object"}
        try:
            user = tokens.verify(session_token, audience=tokens.ISSUER, typ="session+jwt", now=self.clock())
        except (tokens.TokenError, TypeError) as error:
            self.log(None, call, "refused", "session token", str(error))
            return 401, {"error": str(error)}
        if any(not isinstance(user.get(k), str) or not user[k] for k in ("sub", "tenant", "role")) or user["role"] not in POLICY["roles"]:
            self.log(None, call, "refused", "session claims", "invalid user claims")
            return 401, {"error": "invalid user claims"}
        name = user["sub"]
        tool_name = call.get("name")
        rule = POLICY["tools"].get(tool_name) if isinstance(tool_name, str) else None
        if rule is None:
            self.log(name, call, "refused", "tool", "unknown tool")
            return 404, {"error": f"unknown tool {call.get('name')}"}
        problem = schema_problem(call.get("arguments"), rule["input_schema"])
        if problem:
            self.log(name, call, "refused", "schema", problem)
            return 400, {"error": problem}
        if rule["scope"] not in POLICY["roles"][user["role"]]:
            reason = f"role {user['role']} lacks {rule['scope']}"
            self.log(name, call, "refused", "gateway role", reason)
            return 403, {"error": reason}
        token, jti = self.delegate(user, rule)
        try:
            result = self.services[rule["service"]].handle(token, call["name"], call["arguments"])
        except Refused as refused:
            self.log(name, call, "refused", refused.check, refused.reason, jti)
            return refused.status, {"error": refused.reason}
        self.log(name, call, "allowed", None, None, jti)
        return 200, result


class FixedClock:
    """Simulated Unix seconds; advance() moves it forward."""

    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def session_token(user_name, clock, lifetime=3600):
    user = POLICY["users"][user_name]
    return tokens.sign({"sub": user_name, "tenant": user["tenant"], "role": user["role"],
                        "aud": tokens.ISSUER, "exp": clock() + lifetime}, typ="session+jwt")


def build(clock):
    services = {name: ToolService(name, clock) for name in ("docs-service", "publish-service")}
    return Gateway(clock, services), services
