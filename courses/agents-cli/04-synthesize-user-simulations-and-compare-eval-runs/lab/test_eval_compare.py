"""Offline verification for synthesizing user simulations and comparing eval runs."""

import json
import unittest
from pathlib import Path

from compare_flywheel import (
    diff_eval_results,
    validate_analyze_metric,
    verify_no_regressions,
)

HERE = Path(__file__).resolve().parent


class SynthesizeAndCompareEvalTests(unittest.TestCase):
    def test_synthesized_scenarios_and_diff_eval_results(self) -> None:
        scenarios = json.loads(
            (HERE / "synthesized-scenarios.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(scenarios["eval_cases"]), 3)
        self.assertEqual(scenarios["execution_mode"], "actual-ADK-user-simulation")
        self.assertEqual(scenarios["model"], "gemini-3.8-flash")
        for case in scenarios["eval_cases"]:
            self.assertGreaterEqual(case["turns_generated"], 1)
            self.assertLessEqual(case["turns_generated"], scenarios["max_turns"])
            self.assertEqual(case["turns_generated"], len(case["invocations"]))

        recorded = json.loads(
            (HERE / "recorded-eval-compare.json").read_text(encoding="utf-8")
        )
        computed = diff_eval_results(recorded["baseline"], recorded["candidate"])
        self.assertEqual(
            computed["differences"]["command_flag_accuracy.mean_score"]["delta"],
            "+0.3333",
        )
        self.assertEqual(
            computed["differences"]["multi_turn_task_success.mean_score"]["delta"],
            "+1.0",
        )
        deltas = verify_no_regressions(computed)
        self.assertEqual(deltas["command_flag_accuracy"], 0.3333)
        self.assertEqual(deltas["multi_turn_tool_use_quality"], 0.3333)

    def test_unsupported_analyze_metric_fails(self) -> None:
        self.assertEqual(
            validate_analyze_metric("multi_turn_tool_use_quality"),
            "multi_turn_tool_use_quality",
        )
        with self.assertRaises(ValueError) as ctx:
            validate_analyze_metric("command_flag_accuracy")
        self.assertIn(
            "Currently supported: multi_turn_task_success, multi_turn_tool_use_quality",
            str(ctx.exception),
        )

    def test_candidate_regression_caught_by_gate(self) -> None:
        recorded = json.loads(
            (HERE / "recorded-eval-compare.json").read_text(encoding="utf-8")
        )
        regressed_comparison = recorded["failures"]["regressed_candidate"]
        with self.assertRaises(ValueError) as ctx:
            verify_no_regressions(regressed_comparison)
        self.assertIn(
            "command_flag_accuracy.mean_score regressed from 1.0 to 0.6667",
            str(ctx.exception),
        )


if __name__ == "__main__":
    unittest.main()
