"""Offline verification for Terraform provisioning and agents-cli deploy."""

import json
import unittest
from pathlib import Path

from deploy_validator import check_terraform_rollout_order, validate_deploy_flags

HERE = Path(__file__).resolve().parent


class DeployAndTerraformTests(unittest.TestCase):
    def test_recorded_dry_runs_and_terraform_ignore_changes(self) -> None:
        recorded = json.loads(
            (HERE / "recorded-deploy-infra.json").read_text(encoding="utf-8")
        )
        self.assertEqual(recorded["agent_runtime_dry_run"]["exit_code"], 0)
        self.assertEqual(
            recorded["agent_runtime_dry_run"]["runtime_shape"]["container_concurrency"],
            8,
        )
        self.assertEqual(recorded["cloud_run_dry_run"]["exit_code"], 0)
        self.assertIn("--no-cpu-throttling", recorded["cloud_run_dry_run"]["would_run"])

        service_tf = (HERE / "service.tf").read_text(encoding="utf-8")
        self.assertIn("template[0].containers[0].image", service_tf)
        self.assertIn("session_affinity = true", service_tf)

    def test_valid_deploy_flags_for_agent_runtime_and_cloud_run(self) -> None:
        ar = validate_deploy_flags(
            "agent_runtime",
            {"--cpu": "2", "--memory": "4Gi", "--update-only": True},
        )
        self.assertEqual(ar["deployment_target"], "agent_runtime")

        cr = validate_deploy_flags(
            "cloud_run",
            {"--cpu": "1", "--memory": "4Gi", "--secrets": "DOCUCTL_TOKEN=docuctl-ci-token:latest"},
        )
        self.assertEqual(cr["deployment_target"], "cloud_run")

    def test_cpu_flag_on_gke_fails(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_deploy_flags("gke", {"--cpu": "2"})
        self.assertIn(
            "--cpu is only supported for Agent Runtime and Cloud Run deployments (current target: gke).",
            str(ctx.exception),
        )
        self.assertIn("HorizontalPodAutoscaler", str(ctx.exception))

    def test_terraform_after_imperative_deploy_conflict(self) -> None:
        aligned = check_terraform_rollout_order(
            imperative_deploy_ran_first=False,
            terraform_state_has_service=True,
            deployment_target="agent_runtime",
            update_only=True,
        )
        self.assertEqual(aligned["status"], "aligned")

        with self.assertRaises(ValueError) as ctx:
            check_terraform_rollout_order(
                imperative_deploy_ran_first=True,
                terraform_state_has_service=False,
                deployment_target="cloud_run",
            )
        self.assertIn("409 Already Exists", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
