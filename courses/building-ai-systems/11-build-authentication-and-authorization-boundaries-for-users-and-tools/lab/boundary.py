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
POLICY = json.loads((HERE / "policy.json").read_text(encoding="utf-8"))


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
        except tokens.TokenError as error:
            raise Refused(401, "service token", str(error)) from None
        rule = POLICY["tools"][tool]
        if rule["service"] != self.name:
            raise Refused(404, "service tool", f"{self.name} has no tool {tool}")
        if "act" not in claims:
            raise Refused(403, "service delegation", "an agent call must carry the act claim")
        if rule["scope"] not in claims.get("scope", "").split():
            raise Refused(403, "service scope", f"token lacks {rule['scope']}")
        order = POLICY["orders"].get(arguments["order_id"])
        if order is None or order["tenant"] != claims["tenant"]:
            raise Refused(404, "service tenant", "order not found")  # same reply as a missing order
        if tool == "lookup_order":
            return {"order_id": arguments["order_id"], "status": order["status"]}
        return {"order_id": arguments["order_id"], "refunded": True, "reason": arguments["reason"]}


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
        try:
            user = tokens.verify(session_token, audience=tokens.ISSUER, typ="session+jwt", now=self.clock())
        except tokens.TokenError as error:
            self.log(None, call, "refused", "session token", str(error))
            return 401, {"error": str(error)}
        name = user["sub"]
        rule = POLICY["tools"].get(call.get("name"))
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
    services = {name: ToolService(name, clock) for name in ("orders-service", "refunds-service")}
    return Gateway(clock, services), services
