"""Re-score the recorded AgentEvaluator runs offline with ADK's own metric classes."""
import json
import unittest
from pathlib import Path

from google.adk.evaluation.eval_metrics import EvalMetric
from google.adk.evaluation.eval_result import EvalSetResult
from google.adk.evaluation.final_response_match_v1 import RougeEvaluator
from google.adk.evaluation.trajectory_evaluator import TrajectoryEvaluator

from docs_agent.agent import list_pages, read_page

HERE = Path(__file__).parent
ROUGE = EvalSetResult.model_validate_json((HERE / "rouge-result.json").read_text())
JUDGE = EvalSetResult.model_validate_json((HERE / "judge-result.json").read_text())


def invocations(result, eval_id):
    """Copies of the (actual, expected) invocations of every recorded run of one eval case."""
    return [(i.actual_invocation.model_copy(deep=True), i.expected_invocation.model_copy(deep=True))
            for case in result.eval_case_results
            if case.eval_id == eval_id for i in case.eval_metric_result_per_invocation]


def score(evaluator, pairs):
    actual, expected = zip(*pairs)
    return evaluator.evaluate_invocations(list(actual), list(expected)).overall_score


def trajectory(match_type, ignore_args=False):
    criterion = {"threshold": 1.0, "match_type": match_type, "ignore_args": ignore_args}
    return TrajectoryEvaluator(eval_metric=EvalMetric(
        metric_name="tool_trajectory_avg_score", criterion=criterion))


def recorded(result, eval_id, metric):
    return [m.score for case in result.eval_case_results if case.eval_id == eval_id
            for m in case.overall_eval_metric_results if m.metric_name == metric]


class RecordedEvaluation(unittest.TestCase):
    def test_every_recorded_run_used_the_expected_tools(self):
        for result in (ROUGE, JUDGE):
            for case in ("rebuild_index", "python_version"):
                self.assertEqual(recorded(result, case, "tool_trajectory_avg_score"), [1.0, 1.0])

    def test_trajectory_scores_reproduce_offline(self):
        for case in ("rebuild_index", "python_version"):
            self.assertEqual(score(trajectory("EXACT"), invocations(ROUGE, case)), 1.0)

    def test_rouge_scores_reproduce_offline(self):
        evaluator = RougeEvaluator(EvalMetric(metric_name="response_match_score", threshold=0.8))
        for case in ("rebuild_index", "python_version"):
            for pair, expected in zip(invocations(ROUGE, case), recorded(ROUGE, case, "response_match_score")):
                self.assertAlmostEqual(score(evaluator, [pair]), expected)

    def test_a_correct_paraphrase_fails_the_rouge_threshold(self):
        runs = recorded(ROUGE, "rebuild_index", "response_match_score")
        self.assertLess(sum(runs) / len(runs), 0.8)
        answers = [a.final_response.parts[-1].text for a, _ in invocations(ROUGE, "rebuild_index")]
        self.assertTrue(all("docs-assistant index --rebuild" in answer for answer in answers))

    def test_the_llm_judge_accepts_the_same_answers(self):
        for case in ("rebuild_index", "python_version"):
            self.assertEqual(recorded(JUDGE, case, "final_response_match_v2"), [1.0, 1.0])

    def test_exact_fails_on_an_extra_call_that_in_order_allows(self):
        pairs = invocations(ROUGE, "rebuild_index")
        for _, expected in pairs:  # expect only the read_page call
            expected.intermediate_data.tool_uses = expected.intermediate_data.tool_uses[1:]
        self.assertEqual(score(trajectory("EXACT"), pairs), 0.0)
        self.assertEqual(score(trajectory("IN_ORDER"), pairs), 1.0)

    def test_a_different_argument_fails_every_match_type_unless_args_are_ignored(self):
        pairs = invocations(ROUGE, "rebuild_index")
        for _, expected in pairs:
            expected.intermediate_data.tool_uses[1].args = {"path": "troubleshooting.md"}
        for match_type in ("EXACT", "IN_ORDER", "ANY_ORDER"):
            self.assertEqual(score(trajectory(match_type), pairs), 0.0, match_type)
        self.assertEqual(score(trajectory("EXACT", ignore_args=True), pairs), 1.0)

    def test_the_tools_refuse_paths_outside_the_docs_folder(self):
        self.assertIn("cli.md", list_pages()["pages"])
        self.assertIn("error", read_page("../agent.py"))
        self.assertIn("error", read_page("missing.md"))


if __name__ == "__main__":
    unittest.main()
