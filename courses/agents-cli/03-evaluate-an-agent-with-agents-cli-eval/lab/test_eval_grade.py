"""Offline verification for generating traces and grading evaluations with agents-cli eval."""

import json
import unittest
from pathlib import Path

from eval_pipeline import (
    check_eval_gate,
    evaluate_agent_turn_count,
    evaluate_command_flag_accuracy,
    split_case_history,
)

HERE = Path(__file__).resolve().parent


class EvalGenerateAndGradeTests(unittest.TestCase):
    def test_split_case_history_for_shape_a_and_shape_b(self) -> None:
        dataset = json.loads((HERE / "docuctl-eval-dataset.json").read_text(encoding="utf-8"))
        cases = dataset["eval_cases"]

        prior_a, msg_a = split_case_history(cases[0])
        self.assertEqual(prior_a, [])
        self.assertIn("roll production back to r41", msg_a["parts"][0]["text"])

        prior_b, msg_b = split_case_history(cases[2])
        self.assertEqual(len(prior_b), 2)
        self.assertEqual(msg_b["parts"][0]["text"], "And on staging?")

    def test_custom_metrics_and_recorded_summary(self) -> None:
        recorded = json.loads((HERE / "recorded-eval-grade.json").read_text(encoding="utf-8"))
        summary = recorded["grade"]["summary_metrics"]
        checked = check_eval_gate(
            summary,
            {"command_flag_accuracy": 1.0, "agent_turn_count": 1.0},
            expected_cases=3,
        )
        self.assertEqual(checked["command_flag_accuracy"], 1.0)
        self.assertAlmostEqual(checked["agent_turn_count"], 1.0, places=4)

        good_res = evaluate_command_flag_accuracy(
            {"response": "Run `docuctl rollback --env production --to r41`."}
        )
        self.assertEqual(good_res["score"], 1.0)
        bad_res = evaluate_command_flag_accuracy(
            {"response": "Run `docuctl release revert r41`."}
        )
        self.assertEqual(bad_res["score"], 0.0)
        turn_res = evaluate_agent_turn_count(
            {"agent_data": {"turns": [{"turn_index": 0}, {"turn_index": 1}]}}
        )
        self.assertEqual(turn_res["score"], 2.0)

    def test_ambiguous_case_with_both_prompt_and_turns_fails(self) -> None:
        ambiguous_case = {
            "eval_case_id": "broken_ambiguous_case",
            "prompt": {"role": "user", "parts": [{"text": "Hello"}]},
            "agent_data": {
                "turns": [
                    {
                        "turn_index": 0,
                        "events": [
                            {
                                "author": "user",
                                "content": {"role": "user", "parts": [{"text": "Hi"}]},
                            }
                        ],
                    }
                ]
            },
        }
        with self.assertRaises(ValueError) as ctx:
            split_case_history(ambiguous_case)
        self.assertIn(
            "both top-level 'prompt' and agent_data.turns; ambiguous",
            str(ctx.exception),
        )

    def test_dropped_or_low_scoring_cases_rejected_by_gate(self) -> None:
        recorded = json.loads((HERE / "recorded-eval-grade.json").read_text(encoding="utf-8"))
        dropped_summary = recorded["failures"]["dropped_case_silent_exit_zero"][
            "summary_metrics_with_drop"
        ]
        with self.assertRaises(ValueError) as ctx:
            check_eval_gate(
                dropped_summary,
                {"command_flag_accuracy": 1.0},
                expected_cases=3,
            )
        self.assertIn("graded 2/3 cases", str(ctx.exception))

    def test_extra_cases_and_nonfinite_scores_do_not_pass(self) -> None:
        for valid, score in [(4, 1.0), (3, float("nan")), (3, float("inf"))]:
            with self.subTest(valid=valid, score=score), self.assertRaises(ValueError):
                check_eval_gate([{"metric_name": "command_flag_accuracy",
                                  "num_cases_valid": valid, "num_cases_error": 0,
                                  "mean_score": score}],
                                 {"command_flag_accuracy": 1.0}, expected_cases=3)


if __name__ == "__main__":
    unittest.main()
