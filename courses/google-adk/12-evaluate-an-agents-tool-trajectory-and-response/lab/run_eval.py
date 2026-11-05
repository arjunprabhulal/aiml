"""Evaluate the docs assistant on Gemini twice: ROUGE-1 response match, then an LLM judge."""
import asyncio
import json
import hashlib
import sys
from pathlib import Path

from google.adk.evaluation.agent_evaluator import AgentEvaluator
from google.adk.evaluation.eval_config import get_evaluation_criteria_or_default
from google.adk.evaluation.eval_set import EvalSet
from google.adk.evaluation.local_eval_set_results_manager import LocalEvalSetResultsManager

HERE = Path(__file__).parent
CONFIGS = {"rouge": "test_config.json", "judge": "judge_config.json"}


async def evaluate(name: str) -> None:
    eval_set = EvalSet.model_validate_json((HERE / "docs_agent.test.json").read_text())
    history = HERE / "eval-results"
    before = history_versions(history)
    original_failure = None
    try:
        await AgentEvaluator.evaluate_eval_set(
            agent_module="docs_agent",
            eval_set=eval_set,
            eval_config=get_evaluation_criteria_or_default(str(HERE / CONFIGS[name])),
            num_runs=2,
            print_detailed_results=False,
            app_name="docs_agent",
            eval_set_results_manager=LocalEvalSetResultsManager(agents_dir=str(history)),
        )
        print(f"{name}: PASSED")
    except BaseException as failure:
        original_failure = failure
        if isinstance(failure, AssertionError):
            print(f"{name}: FAILED\n{failure}")
        raise
    finally:
        # Preserve the provider/evaluation failure even if its history is absent or incomplete.
        try:
            after = history_versions(history)
            current = [path for path, version in after.items() if before.get(path) != version]
            if current:
                newest = max(current, key=lambda path: path.stat().st_mtime_ns)
                (HERE / f"{name}-result.json").write_text(
                    json.dumps(compact(json.loads(newest.read_text())), indent=1) + "\n")
            else:
                print("No current-run evaluation history was written; saved results were not replaced.", file=sys.stderr)
        except Exception as history_error:
            if original_failure is None:
                raise
            print(f"Current-run history could not be saved ({type(history_error).__name__}); original failure retained.", file=sys.stderr)
        # Keep raw histories, including incomplete runs, for inspection.


def history_versions(folder):
    """Distinguish new/changed results from histories left by an earlier run."""
    return {path: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
            for path in folder.rglob("eval_history/*.json")}


def compact(value):
    """Drop null fields and opaque thought signatures so the saved result stays readable."""
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if v is not None and k != "thought_signature"}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Optional fresh multi-case agent evaluation; judge mode also calls an LLM judge.")
    parser.add_argument("criterion", choices=CONFIGS)
    parser.add_argument("--evaluate", action="store_true")
    options = parser.parse_args()
    if not options.evaluate:
        parser.error("evaluation is opt-in: use --evaluate in a separate copy")
    asyncio.run(evaluate(options.criterion))
