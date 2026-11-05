"""A custom ADK eval metric: the answer cites the expected page, and the agent read that page first."""
import re
import statistics
from typing import Optional

from google.adk.evaluation.conversation_scenarios import ConversationScenario
from google.adk.evaluation.eval_case import Invocation, get_all_tool_calls_with_responses
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.evaluator import EvaluationResult, PerInvocationResult

CITATION = re.compile(r"\(([\w-]+\.md)\)\W*$")


def cited_page(invocation: Optional[Invocation]) -> Optional[str]:
    """The page path in parentheses at the end of the final response, if any."""
    if invocation is None or invocation.final_response is None:
        return None
    text = "".join(part.text or "" for part in invocation.final_response.parts or [])
    match = CITATION.search(text.strip())
    return match.group(1) if match else None


def pages_read(invocation: Invocation) -> set[str]:
    # A proposed call is not a completed read. Require a matched result with page text.
    pages = set()
    for call, response in get_all_tool_calls_with_responses(invocation.intermediate_data):
        if call.name != "read_page" or not call.id or response is None or response.name != "read_page":
            continue
        body, path = response.response, (call.args or {}).get("path")
        if (isinstance(path, str) and isinstance(body, dict) and body.get("path") == path
                and isinstance(body.get("content"), str) and not {"error", "error_code"} & body.keys()):
            pages.add(path)
    return pages


def score_invocation(actual: Invocation, expected: Optional[Invocation]) -> float:
    page = cited_page(actual)
    if page is None or page not in pages_read(actual):
        return 0.0  # no citation, or a citation of a page the agent never read
    return 1.0 if expected is None or page == cited_page(expected) else 0.0


def cited_page_was_read(
    eval_metric: EvalMetric,
    actual_invocations: list[Invocation],
    expected_invocations: Optional[list[Invocation]],
    conversation_scenario: Optional[ConversationScenario],
) -> EvaluationResult:
    threshold = eval_metric.criterion.threshold  # EvalMetric.threshold is deprecated in favor of criterion
    if expected_invocations is not None and len(expected_invocations) != len(actual_invocations):
        raise ValueError("Actual and expected turn counts must match; refusing a partial score.")
    expected_invocations = ([None] * len(actual_invocations)
                            if expected_invocations is None else expected_invocations)
    results = []
    for actual, expected in zip(actual_invocations, expected_invocations):
        score = score_invocation(actual, expected)
        results.append(PerInvocationResult(
            actual_invocation=actual, expected_invocation=expected, score=score,
            eval_status=EvalStatus.PASSED if score >= threshold else EvalStatus.FAILED))
    if not results:
        return EvaluationResult(overall_eval_status=EvalStatus.NOT_EVALUATED)
    overall = statistics.mean(r.score for r in results)
    return EvaluationResult(
        overall_score=overall, per_invocation_results=results,
        overall_eval_status=EvalStatus.PASSED if overall >= threshold else EvalStatus.FAILED)
