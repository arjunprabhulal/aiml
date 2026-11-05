"""Quality Flywheel diffing, loss-cluster validation, and regression gates for agents-cli eval."""

from __future__ import annotations

from typing import Any

SUPPORTED_ANALYZE_METRICS = frozenset(
    {"multi_turn_task_success", "multi_turn_tool_use_quality"}
)


def diff_eval_results(
    base: dict[str, Any], cand: dict[str, Any], prefix: str = ""
) -> dict[str, Any]:
    """Compute a recursive diff between two eval result dicts (mirrors cmd_compare._diff)."""
    differences: dict[str, Any] = {}
    all_keys = set(base.keys()) | set(cand.keys())
    for key in sorted(all_keys):
        full_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        base_val = base.get(key)
        cand_val = cand.get(key)

        if base_val == cand_val:
            continue

        if isinstance(base_val, dict) and isinstance(cand_val, dict):
            nested = diff_eval_results(base_val, cand_val, prefix=full_key)
            differences.update(nested["differences"])
            continue

        entry: dict[str, Any] = {"baseline": base_val, "candidate": cand_val}
        if isinstance(base_val, (int, float)) and isinstance(cand_val, (int, float)):
            delta = round(cand_val - base_val, 4)
            entry["delta"] = f"+{delta}" if delta >= 0 else str(delta)
        differences[full_key] = entry

    if prefix:
        return {"differences": differences}

    return {
        "baseline_keys": sorted(base.keys()),
        "candidate_keys": sorted(cand.keys()),
        "differences": differences,
        "changed_keys": sorted(differences.keys()),
        "unchanged_keys": sorted(k for k in all_keys if k not in differences),
    }


def validate_analyze_metric(metric_name: str) -> str:
    """Validate that the metric passed to `agents-cli eval analyze` is supported."""
    if metric_name not in SUPPORTED_ANALYZE_METRICS:
        supported = ", ".join(sorted(SUPPORTED_ANALYZE_METRICS))
        raise ValueError(
            f"Unsupported metric {metric_name!r} for 'agents-cli eval analyze'. "
            f"Currently supported: {supported}."
        )
    return metric_name


def verify_no_regressions(
    comparison: dict[str, Any],
    higher_is_better_metrics: tuple[str, ...] = (
        "command_flag_accuracy",
        "multi_turn_task_success",
        "multi_turn_tool_use_quality",
    ),
    max_allowed_drop: float = 0.0,
) -> dict[str, float]:
    """Verify that no higher-is-better metric regressed beyond max_allowed_drop."""
    diffs = comparison.get("differences") or {}
    deltas: dict[str, float] = {}
    regressions: list[str] = []

    for metric in higher_is_better_metrics:
        key = f"{metric}.mean_score"
        if key not in diffs:
            deltas[metric] = 0.0
            continue
        entry = diffs[key]
        delta = round(float(entry["candidate"]) - float(entry["baseline"]), 4)
        deltas[metric] = delta
        if delta < -abs(max_allowed_drop):
            regressions.append(
                f"{metric}.mean_score regressed from {entry['baseline']} to "
                f"{entry['candidate']} ({delta:+.4f})"
            )

    if regressions:
        raise ValueError("Regression detected: " + "; ".join(regressions))
    return deltas
