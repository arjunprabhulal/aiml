"""Score two voice agents on the same spoken scenario: the guarded docs agent and the bare baseline."""
import asyncio
import json
import shutil
import sys
from pathlib import Path

from google.adk.evaluation.agent_evaluator import AgentEvaluator
from google.adk.evaluation.eval_config import get_evaluation_criteria_or_default
from google.adk.evaluation.eval_set import EvalSet
from google.adk.evaluation.local_eval_set_results_manager import LocalEvalSetResultsManager

HERE = Path(__file__).parent


async def evaluate(agent_module: str) -> None:
    eval_set = EvalSet.model_validate_json((HERE / "live.evalset.json").read_text())
    history = HERE / "eval-results"
    try:
        await AgentEvaluator.evaluate_eval_set(
            agent_module=agent_module, eval_set=eval_set, num_runs=1, print_detailed_results=False,
            eval_config=get_evaluation_criteria_or_default(str(HERE / "test_config.json")),
            app_name="docs_voice", eval_set_results_manager=LocalEvalSetResultsManager(agents_dir=str(history)))
        print(f"{agent_module}: PASSED")
    except AssertionError as failure:
        print(f"{agent_module}: FAILED\n{failure}")
    finally:  # keep the full EvalSetResult, without audio bytes, under a stable name
        newest = max(history.rglob("eval_history/*.json"), key=lambda p: p.stat().st_mtime)
        (HERE / f"{agent_module}-result.json").write_text(json.dumps(compact(json.loads(newest.read_text())), indent=1) + "\n")
        shutil.rmtree(history)


def compact(value):
    """Drop nulls, thought signatures and inline audio so the saved result stays small and readable."""
    if isinstance(value, dict):
        for key in ("inline_data", "inlineData"):
            if isinstance(value.get(key), dict):
                blob = value[key]
                value = {**value, key: {"mime_type": blob.get("mime_type") or blob.get("mimeType"), "data": "(audio omitted)"}}
        return {k: compact(v) for k, v in value.items() if v is not None and k not in ("thought_signature", "thoughtSignature")}
    if isinstance(value, list):
        return [compact(v) for v in value if not audio_only(v)]
    return value


def audio_only(event) -> bool:
    """An invocation event that carries nothing but audio bytes."""
    parts = (event.get("content") or {}).get("parts") if isinstance(event, dict) and "author" in event else None
    return bool(parts) and all({k for k, v in p.items() if v is not None} <= {"inline_data", "inlineData"} for p in parts)


if __name__ == "__main__":
    asyncio.run(evaluate(sys.argv[1]))
