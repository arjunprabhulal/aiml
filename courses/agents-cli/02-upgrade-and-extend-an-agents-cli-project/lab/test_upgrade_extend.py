"""Offline verification for upgrading and extending an agents-cli project."""

import json
import unittest
from pathlib import Path

from upgrade_extend import classify_three_way_merge, validate_extension_manifest

HERE = Path(__file__).resolve().parent


class UpgradeAndExtendTests(unittest.TestCase):
    def test_three_way_merge_classification(self) -> None:
        self.assertEqual(
            classify_three_way_merge("app/agent.py", "old", "new", "custom"),
            "skip_user_code",
        )
        self.assertEqual(
            classify_three_way_merge("README.md", "v1", "v2", "v1"),
            "auto_update",
        )
        self.assertEqual(
            classify_three_way_merge("Dockerfile", "v1", "v1", "v1 + custom label"),
            "preserve_user_edit",
        )
        self.assertEqual(
            classify_three_way_merge("Dockerfile", "v1", "v1", "v1 + custom label", force=True),
            "force_overwrite",
        )
        self.assertEqual(
            classify_three_way_merge("Dockerfile", "v1", "v2", "v1 + custom label"),
            "conflict",
        )

    def test_recorded_enhance_upgrade_and_extension_runs(self) -> None:
        recorded = json.loads(
            (HERE / "recorded-upgrade-extend.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            recorded["enhance"]["manifest_diff"]["deployment_target"],
            {"before": "none", "after": "cloud_run"},
        )
        self.assertIn("already at version 1.11.0", recorded["upgrade_dry_run"]["output"])
        self.assertIn("already at version 1.11.0", recorded["upgrade_force_dry_run"]["output"])
        self.assertEqual(recorded["extension_execution"]["release_check"]["exit_code"], 0)
        self.assertEqual(recorded["extension_execution"]["deploy_override"]["exit_code"], 0)

    def test_shell_string_in_extension_run_list_fails(self) -> None:
        valid_spec = {
            "schema": "agents-cli-extension/v1alpha1",
            "commands": {
                "override": {
                    "deploy": {
                        "description": "Run unit tests before deploying docuctl-docs",
                        "run": ["uv", "run", "pytest", "tests/unit"],
                    }
                },
                "add": {
                    "release-check": {
                        "description": "Run lint and unit tests for release readiness",
                        "run": ["uv", "run", "pytest", "tests/unit", "-v"],
                    }
                },
            },
        }
        resolved = validate_extension_manifest(valid_spec)
        self.assertEqual(
            resolved["add:release-check"],
            ["uv", "run", "pytest", "tests/unit", "-v"],
        )

        bad_spec = {
            "schema": "agents-cli-extension/v1alpha1",
            "commands": {
                "add": {
                    "release-check": {
                        "description": "Broken shell string",
                        "run": ["uv run pytest tests/unit -v"],
                    }
                }
            },
        }
        with self.assertRaises(ValueError) as ctx:
            validate_extension_manifest(bad_spec)
        self.assertIn("executable 'uv run pytest tests/unit -v' not found", str(ctx.exception))

    def test_overriding_reserved_recovery_command_fails(self) -> None:
        reserved_spec = {
            "schema": "agents-cli-extension/v1alpha1",
            "commands": {
                "override": {
                    "info": {
                        "description": "Try to override info",
                        "run": ["echo", "overridden"],
                    }
                }
            },
        }
        with self.assertRaises(ValueError) as ctx:
            validate_extension_manifest(reserved_spec)
        self.assertIn("cannot be overridden", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
