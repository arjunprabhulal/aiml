"""3-way template merge and extension manifest validator for Google Agents CLI 1.11.0."""

from __future__ import annotations

from typing import Any

SUPPORTED_SCHEMA = "agents-cli-extension/v1alpha1"
RECOVERY_COMMANDS = frozenset({"info", "extension", "install", "scaffold", "setup", "login"})
USER_CODE_PATHS = frozenset(
    {
        ".env",
        "app/agent.py",
        "deployment/terraform/cicd/vars/env.tfvars",
        "deployment/terraform/single-project/vars/env.tfvars",
    }
)


def classify_three_way_merge(
    path: str,
    old_template: str | None,
    new_template: str | None,
    project_file: str | None,
    *,
    force: bool = False,
) -> str:
    """Classify how `agents-cli scaffold upgrade` handles a file across old/new templates."""
    if path in USER_CODE_PATHS:
        return "skip_user_code"
    if force:
        if new_template is not None and project_file != new_template:
            return "force_overwrite"
        return "unchanged"
    if old_template is None and new_template is not None and project_file is None:
        return "add_new"
    if project_file == old_template and new_template != old_template:
        return "auto_update"
    if project_file != old_template and new_template == old_template:
        return "preserve_user_edit"
    if project_file != old_template and new_template != old_template and project_file != new_template:
        return "conflict"
    return "unchanged"


def validate_extension_manifest(spec: dict[str, Any]) -> dict[str, list[str]]:
    """Validate an agents-cli-extension.yaml dictionary and return resolved commands."""
    schema = spec.get("schema")
    if schema != SUPPORTED_SCHEMA:
        raise ValueError(
            f"Unsupported or missing schema {schema!r}; expected {SUPPORTED_SCHEMA!r}."
        )

    commands = spec.get("commands") or {}
    unknown_keys = set(commands.keys()) - {"override", "add"}
    if unknown_keys:
        first_unknown = sorted(unknown_keys)[0]
        raise ValueError(
            f"agents-cli-extension.yaml: unknown key 'commands.{first_unknown}'; "
            "nest commands under 'commands.override' or 'commands.add'."
        )

    resolved: dict[str, list[str]] = {}
    for section in ("override", "add"):
        entries = commands.get(section) or {}
        for cmd_name, entry in entries.items():
            if section == "override" and cmd_name in RECOVERY_COMMANDS:
                raise ValueError(
                    f"Extension claims {cmd_name!r}, which cannot be overridden "
                    "(it is reserved for inspecting, setting up or repairing agents-cli)."
                )
            run_argv = entry.get("run") or []
            if not isinstance(run_argv, list) or not run_argv:
                raise ValueError(f"Command {cmd_name!r} must define a non-empty 'run' argv list.")
            first_token = str(run_argv[0])
            if " " in first_token:
                raise ValueError(
                    f"Command {cmd_name!r} could not run: executable {first_token!r} not found. "
                    "Pass each argv token as a separate list item under 'run:'."
                )
            resolved[f"{section}:{cmd_name}"] = [str(tok) for tok in run_argv]

    return resolved
