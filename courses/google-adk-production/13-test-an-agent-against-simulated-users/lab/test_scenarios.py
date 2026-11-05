"""Check the scenario eval set and the recorded `adk eval` results offline, with ADK's own classes.

Run: python -m unittest -v test_scenarios.py
"""
import json
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from google.adk.evaluation.eval_case import get_all_tool_calls  # noqa: E402
from google.adk.evaluation.eval_metrics import EvalMetric  # noqa: E402
from google.adk.evaluation.eval_result import EvalSetResult  # noqa: E402
from google.adk.evaluation.eval_set import EvalSet  # noqa: E402
from google.adk.evaluation.final_response_match_v1 import RougeEvaluator  # noqa: E402
from google.adk.evaluation.trajectory_evaluator import TrajectoryEvaluator  # noqa: E402

HERE = Path(__file__).resolve().parent
EVAL_SET = EvalSet.model_validate_json((HERE / "docs_assistant/scenarios.evalset.json").read_text())
RESULTS = {p.stem: EvalSetResult.model_validate_json(p.read_text()) for p in (HERE / "results").glob("*.json")}


def case(run: str, starting_prompt: str):
    ids = {c.eval_id for c in EVAL_SET.eval_cases if c.conversation_scenario.starting_prompt == starting_prompt}
    return next(r for r in RESULTS[run].eval_case_results if r.eval_id in ids)


def scores(result) -> dict:
    return {m.metric_name: m.score for m in result.overall_eval_metric_results}


def turns(result) -> list:
    return [i.actual_invocation for i in result.eval_metric_result_per_invocation]


VAGUE = "The docs assistant isn't working for me."
LOCAL = "How do I make the assistant use a local model instead of Gemini?"


class Scenarios(unittest.TestCase):
    def test_add_eval_case_expands_the_persona_name_into_behaviors(self):
        personas = {c.conversation_scenario.user_persona.id: c.conversation_scenario.user_persona
                    for c in EVAL_SET.eval_cases}
        self.assertEqual(set(personas), {"NOVICE", "EXPERT"})
        self.assertTrue(all(p.behaviors for p in personas.values()))
        self.assertTrue(all(not c.conversation for c in EVAL_SET.eval_cases), "scenario cases have no expected turns")

    def test_the_vague_question_gets_a_clarifying_question_before_any_tool_call(self):
        first, second = turns(case("simulated-users", VAGUE))[:2]
        self.assertEqual(get_all_tool_calls(first.intermediate_data), [])
        self.assertTrue(first.final_response.parts[0].text.rstrip().endswith("?"))
        self.assertIn("Ollama", second.user_content.parts[0].text)  # written by the simulated user
        self.assertIn("troubleshooting.md", second.final_response.parts[0].text)

    def test_both_scenarios_pass_hallucination_and_simulator_quality(self):
        for prompt in (VAGUE, LOCAL):
            got = scores(case("simulated-users", prompt))
            self.assertGreaterEqual(got["hallucinations_v1"], 0.8)
            self.assertGreaterEqual(got["per_turn_user_simulator_quality_v1"], 0.8)

    def test_reference_metrics_cannot_score_a_scenario_case(self):
        actual = turns(case("simulated-users", LOCAL))
        trajectory = TrajectoryEvaluator(eval_metric=EvalMetric(
            metric_name="tool_trajectory_avg_score", criterion={"threshold": 1.0}))
        with self.assertRaisesRegex(ValueError, "expected_invocations"):
            trajectory.evaluate_invocations(actual, None)
        with self.assertRaisesRegex(ValueError, "expected_invocations"):
            RougeEvaluator(EvalMetric(metric_name="response_match_score", threshold=0.8)).evaluate_invocations(actual, None)
        self.assertIsNone(scores(case("default-criteria", LOCAL))["tool_trajectory_avg_score"])

    def test_a_one_turn_cap_ends_the_conversation_before_the_plan_is_done(self):
        for prompt in (VAGUE, LOCAL):
            result = case("one-turn-limit", prompt)
            self.assertEqual(len(turns(result)), 1)
            self.assertEqual(scores(result)["per_turn_user_simulator_quality_v1"], 0.0)
            self.assertEqual(scores(result)["hallucinations_v1"], 1.0)

    def test_the_task_success_metric_was_not_evaluated_without_agent_platform(self):
        for prompt in (VAGUE, LOCAL):
            self.assertIsNone(scores(case("task-success-metric", prompt))["multi_turn_task_success_v1"])
        self.assertIn("403 PERMISSION_DENIED", (HERE / "run-output.txt").read_text())


if __name__ == "__main__":
    unittest.main()
