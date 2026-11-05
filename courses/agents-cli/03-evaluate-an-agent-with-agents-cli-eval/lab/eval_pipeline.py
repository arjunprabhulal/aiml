"""Trace generation validation, custom metrics, and CI threshold gate for agents-cli eval."""

from __future__ import annotations

from typing import Any
import math


def split_case_history(case: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate an eval case (Shape A prompt or Shape B agent_data.turns N+1) and split history.

    Mirrors `google.agents.cli.eval.cmd_generate.split_case_history`.
    """
    prompt = case.get("prompt")
    agent_data = case.get("agent_data") or {}
    turns = agent_data.get("turns") or []

    if prompt and turns:
        raise ValueError(
            "Case has both top-level 'prompt' and agent_data.turns; ambiguous."
        )
    if prompt:
        return [], prompt

    prior_events: list[dict[str, Any]] = []
    for turn in turns:
        prior_events.extend(turn.get("events") or [])
    if not prior_events or prior_events[-1].get("author") != "user":
        raise ValueError(
            "Case has no user message to send (missing prompt and no trailing "
            "user event in agent_data.turns)."
        )
    last_event = dict(prior_events.pop())
    content = last_event.get("content")
    if not content:
        raise ValueError("Trailing user event has no content to send to /run_sse.")
    return prior_events, content


def evaluate_command_flag_accuracy(instance: dict[str, Any]) -> dict[str, Any]:
    """Deterministic custom metric checking docuctl 2.x commands and rejecting removed 1.x commands."""
    resp = str(instance.get("response") or "")
    has_v2_cmd = ("docuctl rollback" in resp) or ("docuctl tokens" in resp)
    used_removed = "release revert" in resp and "removed" not in resp.lower()
    score = 1.0 if (has_v2_cmd and not used_removed) else 0.0
    return {
        "score": score,
        "explanation": f"has_v2_cmd={has_v2_cmd}, used_removed={used_removed}",
    }


def evaluate_agent_turn_count(instance: dict[str, Any]) -> dict[str, float]:
    """Count conversation turns in agent_data.turns."""
    turns = (instance.get("agent_data") or {}).get("turns", [])
    return {"score": float(len(turns))}


def check_eval_gate(
    summary_metrics: list[dict[str, Any]],
    thresholds: dict[str, float],
    *,
    expected_cases: int,
) -> dict[str, float]:
    """Enforce zero dropped/errored cases and minimum mean_score thresholds on eval grade output."""
    by_name = {m["metric_name"]: m for m in summary_metrics}
    checked: dict[str, float] = {}
    for metric_name, min_score in thresholds.items():
        if metric_name not in by_name:
            raise ValueError(f"Missing required metric {metric_name!r} in summary_metrics.")
        entry = by_name[metric_name]
        valid = int(entry.get("num_cases_valid") or 0)
        errored = int(entry.get("num_cases_error") or 0)
        if errored > 0 or valid != expected_cases:
            raise ValueError(
                f"Metric {metric_name!r} graded {valid}/{expected_cases} cases "
                f"(num_cases_error={errored}); refusing unexpected coverage or grading errors."
            )
        mean_score = float(entry["mean_score"])
        if not math.isfinite(mean_score) or mean_score < min_score:
            raise ValueError(
                f"Metric {metric_name!r} mean_score {mean_score:.4f} is non-finite or below "
                f"threshold {min_score:.4f}."
            )
        checked[metric_name] = round(mean_score, 4)
    return checked
