"""Re-score the recorded runs with the custom metric offline, and check the configs and the optimized instruction.

Run: python -m unittest -v test_citation_metric.py
"""
import json
import subprocess
import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from google.adk.evaluation.eval_config import EvalConfig, get_eval_metrics_from_config  # noqa: E402
from google.adk.evaluation.eval_result import EvalSetResult  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import citation_metric  # noqa: E402

HERE = Path(__file__).resolve().parent
CONFIG = EvalConfig.model_validate_json((HERE / "eval_config.json").read_text())
METRIC = next(m for m in get_eval_metrics_from_config(CONFIG) if m.metric_name == "cited_page_was_read")
RESULTS = {p.stem: EvalSetResult.model_validate_json(p.read_text()) for p in (HERE / "results").glob("*.json")}


def invocations(run):
    return [(i.actual_invocation, i.expected_invocation)
            for case in RESULTS[run].eval_case_results for i in case.eval_metric_result_per_invocation]


def rescore(run):
    pairs = invocations(run)
    return citation_metric.cited_page_was_read(METRIC, [a for a, _ in pairs], [e for _, e in pairs], None)


def first_prompt_tokens(run):
    return sorted(next(e.usage_metadata.prompt_token_count for e in a.intermediate_data.invocation_events if e.usage_metadata)
                  for a, _ in invocations(run))


def setUpModule():
    warnings.simplefilter("ignore")


class CitationMetric(unittest.TestCase):
    def test_the_baseline_agent_never_cites_a_page(self):
        for run in ("baseline-train", "baseline-validation"):
            result = rescore(run)
            self.assertEqual(result.overall_score, 0.0)
            self.assertTrue(all(citation_metric.cited_page(a) is None for a, _ in invocations(run)))

    def test_the_optimized_instruction_passes_the_validation_set(self):
        self.assertEqual(rescore("optimized-validation").overall_score, 1.0)
        recorded = [m.score for c in RESULTS["optimized-validation"].eval_case_results
                    for m in c.overall_eval_metric_results if m.metric_name == "cited_page_was_read"]
        self.assertEqual(recorded, [1.0] * 3)

    def test_a_citation_of_an_unread_page_scores_zero(self):
        actual, expected = invocations("optimized-validation")[0]
        unread = actual.model_copy(deep=True)
        unread.intermediate_data.invocation_events = [
            e for e in unread.intermediate_data.invocation_events
            if not (e.content and any(p.function_call and p.function_call.name == "read_page" for p in e.content.parts))]
        self.assertEqual(citation_metric.score_invocation(actual, expected), 1.0)
        self.assertEqual(citation_metric.score_invocation(unread, expected), 0.0)

    def test_a_failed_read_does_not_count_as_reading_the_page(self):
        actual, expected = invocations("optimized-validation")[0]
        failed = actual.model_copy(deep=True)
        for event in failed.intermediate_data.invocation_events:
            for part in event.content.parts if event.content else []:
                if part.function_response and part.function_response.name == "read_page":
                    part.function_response.response = {"error_code": 503, "error_message": "Unavailable"}
        self.assertEqual(citation_metric.score_invocation(failed, expected), 0.0)

    def test_missing_or_mismatched_read_results_do_not_count(self):
        actual, expected = invocations("optimized-validation")[0]
        for mode in ("missing", "wrong-id", "wrong-path", "no-content"):
            changed = actual.model_copy(deep=True)
            for event in changed.intermediate_data.invocation_events:
                if not event.content:
                    continue
                if mode == "missing":
                    event.content.parts = [p for p in event.content.parts if not p.function_response]
                for part in event.content.parts:
                    response = part.function_response
                    if response and response.name == "read_page":
                        if mode == "wrong-id":
                            response.id = "unrelated-call"
                        elif mode == "wrong-path":
                            response.response["path"] = "unrelated.md"
                        else:
                            response.response.pop("content", None)
            with self.subTest(mode=mode):
                self.assertEqual(citation_metric.score_invocation(changed, expected), 0.0)

    def test_mismatched_turn_counts_are_rejected_instead_of_truncated(self):
        actual, expected = invocations("optimized-validation")[0]
        for actuals, expecteds in (([actual, actual], [expected]), ([actual], [expected, expected]),
                                   ([actual], []), ([], [expected])):
            with self.subTest(actual=len(actuals), expected=len(expecteds)):
                with self.assertRaisesRegex(ValueError, "turn counts"):
                    citation_metric.cited_page_was_read(METRIC, actuals, expecteds, None)

    def test_metric_info_without_its_required_fields_is_rejected(self):
        with self.assertRaises(ValidationError):
            EvalConfig.model_validate_json((HERE / "config-partial-metric-info.json").read_text())
        self.assertEqual(CONFIG.custom_metrics["cited_page_was_read"].metric_info.metric_value_info.interval.max_value, 1.0)

    def test_the_metric_module_must_be_importable_by_the_eval_process(self):
        code = ("from google.adk.evaluation.custom_metric_evaluator import _get_metric_function as get; "
                "get('citation_metric.cited_page_was_read')")
        isolated = subprocess.run([sys.executable, "-I", "-c", code], cwd=HERE, capture_output=True, text=True)
        self.assertIn("Could not import custom metric function", isolated.stderr)
        on_path = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True,
                                 env={"PYTHONPATH": str(HERE), "PATH": ""})
        self.assertEqual(on_path.returncode, 0, on_path.stderr)
        self.assertIn("No module named 'citation_metric'", (HERE / "run-output.txt").read_text())

    def test_the_optimizer_copied_docs_facts_into_the_instruction(self):
        instruction = (HERE / "optimized-instruction.txt").read_text()
        self.assertIn("Python 3.12 or later", instruction)
        self.assertIn("Python 3.12 or later", (HERE / "docs_assistant/docs/install.md").read_text())
        baseline, optimized = first_prompt_tokens("baseline-validation"), first_prompt_tokens("optimized-validation")
        self.assertTrue(all(o > b for o, b in zip(optimized, baseline)))
        self.assertIn("answer You need Python 3.13 or later (install.md).", (HERE / "run-output.txt").read_text())


if __name__ == "__main__":
    unittest.main()
