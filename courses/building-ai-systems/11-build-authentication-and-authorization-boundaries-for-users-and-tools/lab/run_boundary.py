"""Send each conversation's proposed tool calls through the boundary, then try the attacks.

    python3 run_boundary.py record   # needs Ollama with the pinned gemma4:e2b
    python3 run_boundary.py          # offline: replays the recorded proposals, writes decisions.json
    python3 run_boundary.py --check  # offline: compares a fresh replay with decisions.json

The clock is simulated, so token expiry and every audit time are exact.
"""
import argparse
import json
import sys
from pathlib import Path

import agent
import boundary
import tokens

HERE = Path(__file__).resolve().parent
RECORDING = HERE / "recorded" / "proposals.json"
START = 1_800_000_000  # simulated Unix seconds


def conversations(model, gateway, clock):
    rows = []
    for convo in json.loads((HERE / "conversations.json").read_text())["conversations"]:
        reply = model.propose(agent.request_for(convo["message"], boundary.POLICY["tools"]))
        session = boundary.session_token(convo["user"], clock)
        decisions = []
        for call in reply["tool_calls"]:
            status, result = gateway.call_tool(session, call)
            decisions.append({"call": call, "status": status, "result": result})
            clock.advance(1)
        rows.append({"id": convo["id"], "user": convo["user"], "proposed": len(reply["tool_calls"]),
                     "model_text": reply["content"], "decisions": decisions})
    return rows


def attacks(gateway, services, clock):
    """Requests that do not come from the model: stolen, reused or forged tokens."""
    ana = boundary.session_token("ana", clock)
    lookup = {"name": "lookup_order", "arguments": {"order_id": "n-1001"}}
    rule = boundary.POLICY["tools"]["lookup_order"]
    user = tokens.verify(ana, tokens.ISSUER, "session+jwt", clock())
    orders_token, _ = gateway.delegate(user, rule)
    head, body, mac = boundary.tokens.sign({"sub": "ana", "tenant": "south-shop", "scope": "orders:read",
                                            "act": {"sub": "support-agent"}, "aud": "orders-service",
                                            "exp": clock() + 60, "jti": "forged-1"}, "tool+jwt").split(".")
    _, real_body, _ = orders_token.split(".")
    unsigned = tokens._b64(json.dumps({"alg": "none", "typ": "tool+jwt"}).encode())
    cases = [
        ("session token sent to a tool service", lambda: services["orders-service"].handle(ana, "lookup_order", lookup["arguments"])),
        ("delegated token used once", lambda: services["orders-service"].handle(orders_token, "lookup_order", lookup["arguments"])),
        ("same delegated token replayed", lambda: services["orders-service"].handle(orders_token, "lookup_order", lookup["arguments"])),
        ("orders token sent to the refunds service", lambda: services["refunds-service"].handle(
            gateway.delegate(user, rule)[0], "issue_refund", {"order_id": "n-1001", "reason": "damaged"})),
        ("claims edited, old signature kept", lambda: services["orders-service"].handle(
            f"{head}.{body}.{orders_token.split('.')[2]}", "lookup_order", {"order_id": "s-2001"})),
        ("algorithm none, no signature", lambda: services["orders-service"].handle(
            f"{unsigned}.{real_body}.", "lookup_order", lookup["arguments"])),
        ("tool token without the act claim", lambda: services["orders-service"].handle(tokens.sign(
            {"sub": "ana", "tenant": "north-shop", "scope": "orders:read", "aud": "orders-service",
             "exp": clock() + 60, "jti": "direct-1"}, "tool+jwt"), "lookup_order", lookup["arguments"])),
        ("refunds token with only a read scope", lambda: services["refunds-service"].handle(tokens.sign(
            {"sub": "ana", "tenant": "north-shop", "scope": "orders:read", "act": {"sub": "support-agent"},
             "aud": "refunds-service", "exp": clock() + 60, "jti": "narrow-1"}, "tool+jwt"),
            "issue_refund", {"order_id": "n-1001", "reason": "damaged"})),
        ("proposed arguments name another tenant", lambda: gateway.call_tool(ana, {
            "name": "lookup_order", "arguments": {"order_id": "s-2001", "tenant": "south-shop"}})),
        ("proposed call to a tool that does not exist", lambda: gateway.call_tool(ana, {
            "name": "export_all_orders", "arguments": {}})),
        ("delegated token after its expiry", lambda: expired(gateway, services, clock, user, rule)),
        ("session token after its expiry", lambda: gateway_after(gateway, clock, ana)),
    ]
    rows = []
    for name, attempt in cases:
        try:
            outcome = attempt()
            rows.append({"case": name, "status": outcome[0] if isinstance(outcome, tuple) else 200,
                         "result": outcome[1] if isinstance(outcome, tuple) else outcome})
        except boundary.Refused as refused:
            rows.append({"case": name, "status": refused.status, "check": refused.check, "result": {"error": refused.reason}})
    return rows


def expired(gateway, services, clock, user, rule):
    token, _ = gateway.delegate(user, rule)
    clock.advance(boundary.POLICY["delegated_token_seconds"])
    return services["orders-service"].handle(token, "lookup_order", {"order_id": "n-1001"})


def gateway_after(gateway, clock, session):
    clock.advance(3600)
    return gateway.call_tool(session, {"name": "lookup_order", "arguments": {"order_id": "n-1001"}})


def results(model):
    clock = boundary.FixedClock(START)
    gateway, services = boundary.build(clock)
    rows = conversations(model, gateway, clock)
    attack_rows = attacks(gateway, services, clock)
    return {"start": START, "conversations": rows, "attacks": attack_rows, "audit": gateway.audit}


def record(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", choices=["record"])
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args(argv)
    if options.command == "record":
        model = agent.OllamaModel()
        results(model)
        RECORDING.write_text(json.dumps({"model": agent.MODEL, "calls": dict(sorted(model.recorded.items()))},
                                        indent=2, ensure_ascii=False) + "\n")
        print(f"recorded {len(model.recorded)} model replies")
        return
    fresh = results(agent.ReplayModel(RECORDING))
    for row in fresh["conversations"]:
        print(f"{row['id']} ({row['user']}): {row['proposed']} proposed")
        for d in row["decisions"]:
            print(f"   {d['call']['name']} {json.dumps(d['call']['arguments'])} -> {d['status']} {json.dumps(d['result'])}")
    for row in fresh["attacks"]:
        print(f"attack: {row['case']}: {row['status']} {row.get('check', '')} {json.dumps(row['result'])}")
    if options.check:
        if (HERE / "decisions.json").read_text() != record(fresh):
            sys.exit("decisions.json differs from a fresh replay")
        print("decisions.json matches")
        return
    (HERE / "decisions.json").write_text(record(fresh))
    print("wrote decisions.json")


if __name__ == "__main__":
    main()
