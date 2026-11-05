"""Tests for the user, agent and tool boundary: python3 -m unittest -v test_boundary.py

The tests replay the recorded model proposals and use a simulated clock, so every
decision, expiry and audit time is exact. No model or network is used.
"""
import json
import unittest
from pathlib import Path

import agent
import boundary
import run_boundary
import tokens

HERE = Path(__file__).resolve().parent


class Recorded(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.replayed = run_boundary.results(agent.ReplayModel(run_boundary.RECORDING))
        cls.convo = {row["id"]: row for row in cls.replayed["conversations"]}
        cls.attack = {row["case"]: row for row in cls.replayed["attacks"]}

    def statuses(self, convo_id):
        return [(d["call"]["arguments"]["order_id"], d["status"]) for d in self.convo[convo_id]["decisions"]]

    def test_saved_decisions_match_a_fresh_replay_byte_for_byte(self):
        self.assertEqual((HERE / "decisions.json").read_text(), run_boundary.record(self.replayed))

    def test_a_role_without_the_tools_scope_is_refused_before_any_token_is_minted(self):
        decision = self.convo["viewer-refund"]["decisions"][0]
        self.assertEqual((decision["status"], decision["result"]["error"]), (403, "role viewer lacks refunds:write"))
        entry = [e for e in self.replayed["audit"] if e["user"] == "ben"][0]
        self.assertEqual((entry["check"], entry["jti"]), ("gateway role", None))

    def test_another_tenants_order_gets_the_same_404_as_a_missing_one(self):
        self.assertEqual(self.statuses("other-shop-refund"), [("s-2001", 404)])
        self.assertEqual(self.statuses("other-shop-lookup"), [("n-1001", 404)])

    def test_text_that_claims_admin_rights_grants_nothing(self):
        self.assertEqual(self.statuses("injected-admin"), [("s-2001", 404), ("n-1002", 200)])

    def test_the_session_token_is_never_accepted_by_a_tool_service(self):
        refused = self.attack["session token sent to a tool service"]
        self.assertEqual(refused["status"], 401)
        self.assertTrue(refused["result"]["error"].startswith("type:"))  # refused as the wrong kind of token

    def test_a_delegated_token_works_once_and_only_at_its_own_service(self):
        self.assertEqual(self.attack["delegated token used once"]["status"], 200)
        self.assertIn("replay", self.attack["same delegated token replayed"]["result"]["error"])
        self.assertIn("audience", self.attack["orders token sent to the refunds service"]["result"]["error"])

    def test_edited_claims_and_the_none_algorithm_are_refused(self):
        self.assertIn("signature", self.attack["claims edited, old signature kept"]["result"]["error"])
        self.assertIn("algorithm", self.attack["algorithm none, no signature"]["result"]["error"])

    def test_the_service_requires_delegation_and_its_own_scope(self):
        self.assertEqual(self.attack["tool token without the act claim"]["check"], "service delegation")
        self.assertEqual(self.attack["refunds token with only a read scope"]["check"], "service scope")

    def test_model_arguments_cannot_name_a_tenant_or_an_unknown_tool(self):
        self.assertEqual(self.attack["proposed arguments name another tenant"]["status"], 400)
        self.assertEqual(self.attack["proposed call to a tool that does not exist"]["status"], 404)

    def test_tokens_expire_on_the_simulated_clock(self):
        for case in ("delegated token after its expiry", "session token after its expiry"):
            self.assertEqual(self.attack[case]["status"], 401, case)
            self.assertIn("expiry", self.attack[case]["result"]["error"], case)

    def test_the_audit_log_records_every_decision_and_no_token(self):
        decisions = sum(len(row["decisions"]) for row in self.replayed["conversations"])
        gateway_attacks = 3  # the attacks that go through the gateway
        self.assertEqual(len(self.replayed["audit"]), decisions + gateway_attacks)
        text = json.dumps(self.replayed["audit"])
        self.assertNotIn("eyJ", text)  # every token starts with the base64 of '{"'
        self.assertTrue(all(e["decision"] in ("allowed", "refused") for e in self.replayed["audit"]))


class Tokens(unittest.TestCase):
    def test_a_token_expires_exactly_at_exp(self):
        token = tokens.sign({"aud": "x", "exp": 100}, typ="t")
        self.assertEqual(tokens.verify(token, "x", "t", now=99)["exp"], 100)
        with self.assertRaises(tokens.TokenError):
            tokens.verify(token, "x", "t", now=100)

    def test_a_token_without_a_jti_cannot_be_used_where_replay_is_checked(self):
        token = tokens.sign({"aud": "x", "exp": 100}, typ="t")
        with self.assertRaisesRegex(tokens.TokenError, "replay"):
            tokens.verify(token, "x", "t", now=1, seen_jti=set())

    def test_the_delegated_token_carries_only_this_tools_scope(self):
        clock = boundary.FixedClock(run_boundary.START)
        gateway, _ = boundary.build(clock)
        user = {"sub": "ana", "tenant": "north-shop", "role": "agent"}
        token, jti = gateway.delegate(user, boundary.POLICY["tools"]["lookup_order"])
        claims = tokens.verify(token, "orders-service", "tool+jwt", clock())
        self.assertEqual((claims["scope"], claims["act"], claims["exp"] - clock(), claims["jti"]),
                         ("orders:read", {"sub": "support-agent"}, boundary.POLICY["delegated_token_seconds"], jti))


if __name__ == "__main__":
    unittest.main()
