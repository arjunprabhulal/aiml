"""Offline verification for the agents-cli scaffold and run lesson."""

import json
import unittest
from pathlib import Path

from docuctl_docs.agent import (
    PAGES,
    app,
    read_page,
    root_agent,
    validate_manifest_contract,
    validate_project_name,
)

HERE = Path(__file__).resolve().parent


class CreateAndRunAgentCliTests(unittest.TestCase):
    def test_real_adk_types_and_bounded_request_config(self) -> None:
        from google.adk.agents import Agent
        from google.adk.apps import App
        self.assertIsInstance(root_agent, Agent)
        self.assertIsInstance(app, App)
        self.assertEqual(root_agent.generate_content_config.max_output_tokens, 1024)
        self.assertEqual(root_agent.generate_content_config.thinking_config.thinking_level.value, "LOW")
        self.assertEqual(root_agent.model.retry_options.attempts, 1)

    def test_pages_and_read_page_tool(self) -> None:
        self.assertEqual(PAGES, ["config", "deploy", "rollback", "tokens"])
        rollback = read_page("rollback")
        self.assertEqual(rollback["page"], "rollback")
        self.assertIn("docuctl rollback --env production --to r41", rollback["text"])

        missing = read_page("billing")
        self.assertEqual(
            missing["error"],
            "No page 'billing'. Pages: config, deploy, rollback, tokens.",
        )

    def test_recorded_multi_turn_session_and_agent_card(self) -> None:
        recorded = json.loads((HERE / "recorded-session.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded["cli_version"], "1.11.0")
        self.assertEqual(recorded["root_agent_name"], "docuctl_docs")
        self.assertEqual(root_agent.name, "docuctl_docs")
        self.assertEqual(recorded["app_name"], app.name)
        self.assertEqual(len(recorded["turns"]), 2)
        self.assertEqual(
            recorded["turns"][0]["session_id"],
            recorded["turns"][1]["session_id"],
        )
        skill_ids = [s["id"] for s in recorded["agent_card"]["skills"]]
        self.assertEqual(skill_ids, ["docuctl_docs", "docuctl_docs-read_page"])

    def test_project_name_length_limit(self) -> None:
        self.assertEqual(validate_project_name("docuctl-docs"), "docuctl-docs")
        with self.assertRaises(ValueError) as ctx:
            validate_project_name("docuctl-documentation-assistant-prod")
        self.assertIn("exceeds 26 characters", str(ctx.exception))

    def test_app_name_matches_agent_directory(self) -> None:
        routes = validate_manifest_contract(app.name, "app")
        self.assertEqual(
            routes["a2a_card_route"],
            "/a2a/app/.well-known/agent-card.json",
        )
        with self.assertRaises(ValueError) as ctx:
            validate_manifest_contract("docuctl_docs", "app")
        self.assertIn("does not match manifest agent_directory='app'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
