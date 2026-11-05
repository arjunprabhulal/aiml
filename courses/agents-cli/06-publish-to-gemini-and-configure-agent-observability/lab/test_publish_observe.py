"""Offline verification for Gemini registration and two-tier agent observability."""

import json
import unittest
from pathlib import Path

from publish_observe import (
    resolve_publish_gemini_request,
    select_card_auth_token_type,
    validate_observability_env,
)

HERE = Path(__file__).resolve().parent


class PublishAndObserveTests(unittest.TestCase):
    def test_publish_modes_and_token_selection(self) -> None:
        recorded = json.loads(
            (HERE / "recorded-publish-observe.json").read_text(encoding="utf-8")
        )
        cr = resolve_publish_gemini_request(
            registration_type="a2a",
            agent_card_url="https://docuctl-docs-913703049174.us-central1.run.app/a2a/app/.well-known/agent-card.json",
            gemini_app_id="projects/913703049174/locations/global/collections/default_collection/engines/eng-ops-assistant",
        )
        historical = recorded["publish_modes"]["a2a_cloud_run"]["resolved"]
        self.assertEqual(cr["protocol"], historical["protocol"])
        self.assertEqual(cr["discovery_engine_endpoint"], historical["discovery_engine_endpoint"])
        self.assertIn("docuctl-docs", cr["agent_card_url"])
        self.assertEqual(cr["card_auth_token_type"], "audience_id_token")

        ar_meta = {
            "remote_agent_runtime_id": "projects/913703049174/locations/us-central1/reasoningEngines/EXAMPLE_ENGINE",
            "is_a2a": True,
        }
        ar = resolve_publish_gemini_request(
            registration_type=None,
            gemini_app_id="projects/913703049174/locations/us/collections/default_collection/engines/eng-ops-assistant",
            metadata=ar_meta,
        )
        self.assertEqual(
            ar,
            recorded["publish_modes"]["a2a_agent_runtime_from_metadata"]["resolved"],
        )
        self.assertEqual(
            select_card_auth_token_type(ar["agent_card_url"]),
            "access_token",
        )

    def test_two_tier_observability_and_telemetry_tf(self) -> None:
        recorded = json.loads(
            (HERE / "recorded-publish-observe.json").read_text(encoding="utf-8")
        )
        obs = validate_observability_env(recorded["observability_tiers"]["env"])
        self.assertEqual(obs, recorded["observability_tiers"]["validated"])
        self.assertFalse(obs["spans_include_message_content"])
        self.assertTrue(obs["gcs_completion_upload_enabled"])

        tf_text = (HERE / "telemetry.tf").read_text(encoding="utf-8")
        self.assertIn("gen_ai.client.inference.operation.details", tf_text)
        self.assertIn("ignore_changes = [schema]", tf_text)

    def test_programmatic_publish_without_registration_type_fails(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_publish_gemini_request(
                registration_type=None,
                gemini_app_id="projects/913703049174/locations/global/collections/default_collection/engines/eng-ops-assistant",
                metadata=None,
            )
        self.assertIn(
            "--registration-type is required in programmatic mode.",
            str(ctx.exception),
        )

    def test_upload_hook_without_logs_bucket_fails(self) -> None:
        recorded = json.loads(
            (HERE / "recorded-publish-observe.json").read_text(encoding="utf-8")
        )
        bad_env = recorded["failures"]["upload_hook_without_logs_bucket"]["env"]
        with self.assertRaises(ValueError) as ctx:
            validate_observability_env(bad_env)
        self.assertIn("requires LOGS_BUCKET_NAME", str(ctx.exception))

    def test_no_content_does_not_disable_adk_default_capture(self) -> None:
        env = {"OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "NO_CONTENT"}
        self.assertTrue(validate_observability_env(env)["spans_include_message_content"])
        env["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] = "false"
        self.assertFalse(validate_observability_env(env)["spans_include_message_content"])


if __name__ == "__main__":
    unittest.main()
