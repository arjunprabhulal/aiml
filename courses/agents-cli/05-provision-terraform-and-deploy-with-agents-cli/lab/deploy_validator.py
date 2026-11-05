"""Deployment flag validation, Terraform ownership checks, and metadata builder for agents-cli deploy."""

from __future__ import annotations

from typing import Any

TARGET_ONLY_FLAGS: dict[str, tuple[tuple[str, ...], str]] = {
    "--cpu": (
        ("agent_runtime", "cloud_run"),
        "On GKE, configure sizing via Terraform and the HorizontalPodAutoscaler under deployment/terraform/.",
    ),
    "--memory": (
        ("agent_runtime", "cloud_run"),
        "On GKE, configure sizing via Terraform and the HorizontalPodAutoscaler under deployment/terraform/.",
    ),
    "--concurrency": (
        ("agent_runtime", "cloud_run"),
        "On GKE, configure sizing via Terraform and the HorizontalPodAutoscaler under deployment/terraform/.",
    ),
    "--secrets": (
        ("agent_runtime", "cloud_run"),
        "On GKE, mount secrets via Kubernetes Secrets or the Secret Manager CSI driver.",
    ),
    "--update-only": (
        ("agent_runtime",),
        "",
    ),
    "--image": (
        ("cloud_run", "gke"),
        "Agent Runtime builds from the project Dockerfile and does not support prebuilt images.",
    ),
}

AGENT_RUNTIME_RESERVED_ENV = frozenset({"GOOGLE_CLOUD_PROJECT"})


def validate_deploy_flags(
    deployment_target: str, provided_flags: dict[str, Any]
) -> dict[str, Any]:
    """Validate target-specific flags for `agents-cli deploy` (mirrors cmd_deploy.py)."""
    if deployment_target not in ("agent_runtime", "cloud_run", "gke"):
        raise ValueError(f"Unsupported deployment target: {deployment_target!r}")

    for flag, value in provided_flags.items():
        if value is None or value is False:
            continue
        if flag in TARGET_ONLY_FLAGS:
            allowed_targets, hint = TARGET_ONLY_FLAGS[flag]
            if deployment_target not in allowed_targets:
                target_names = " and ".join(
                    {"agent_runtime": "Agent Runtime", "cloud_run": "Cloud Run", "gke": "GKE"}[t]
                    for t in allowed_targets
                )
                msg = (
                    f"{flag} is only supported for {target_names} deployments "
                    f"(current target: {deployment_target})."
                )
                if hint:
                    msg += f"\n  {hint}"
                raise ValueError(msg)

    return {
        "deployment_target": deployment_target,
        "validated_flags": {k: v for k, v in provided_flags.items() if v is not None},
    }


def check_terraform_rollout_order(
    *,
    imperative_deploy_ran_first: bool,
    terraform_state_has_service: bool,
    deployment_target: str,
    update_only: bool = False,
) -> dict[str, str]:
    """Verify that Terraform and imperative `agents-cli deploy` do not collide on resource ownership."""
    if imperative_deploy_ran_first and not terraform_state_has_service:
        raise ValueError(
            "Resource ownership conflict: imperative 'agents-cli deploy' created the service "
            "before 'terraform apply'. Running 'terraform apply' now fails with 409 Already Exists "
            "(or creates a duplicate Agent Runtime engine). Provision Terraform first or import the resource."
        )
    if deployment_target == "agent_runtime" and terraform_state_has_service and not update_only:
        raise ValueError(
            "Agent Runtime engine is managed by Terraform; pass --update-only to 'agents-cli deploy' "
            "so a missing engine ID fails fast instead of creating a duplicate ReasoningEngine."
        )
    return {
        "status": "aligned",
        "deployment_target": deployment_target,
        "image_lifecycle": "ignore_changes=[template[0].containers[0].image]",
    }
