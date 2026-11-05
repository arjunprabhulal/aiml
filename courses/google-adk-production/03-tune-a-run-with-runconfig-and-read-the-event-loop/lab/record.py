"""Record tune.py on Gemini, plus two RunConfig failures: a history cap that starts at a
function call, and a model-call timeout that is too short.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes run-output.txt and recorded-runs.json. The tests replay it offline.
"""
import asyncio
import json
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)  # ADK logs each expected failure with a traceback

from google.adk import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402

import tune  # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL_TURNS: list = []


def keep_turn(callback_context, llm_response):
    """after_model_callback: keep each model response (thought signatures dropped) for the replay tests."""
    if llm_response.content:
        parts = [{k: v for k, v in p.model_dump(mode="json", exclude_none=True).items() if k != "thought_signature"}
                 for p in llm_response.content.parts]
        MODEL_TURNS.append({"content": {"role": "model", "parts": parts}})


async def scenario(turns) -> dict:
    tune.LOG.clear()
    MODEL_TURNS.clear()
    agent = tune.root_agent.clone(update={"after_model_callback": keep_turn})
    runner = Runner(app_name=tune.APP, agent=agent, session_service=InMemorySessionService())
    session = await runner.session_service.create_session(app_name=tune.APP, user_id=tune.USER)
    error = None
    try:
        for request_id, text, recent, timeout_ms in turns:
            tune.LOG.append(f"{request_id}: {text}" + (f"  (num_recent_events={recent})" if recent else "")
                            + (f"  (timeout={timeout_ms} ms)" if timeout_ms != 60_000 else ""))
            events = await tune.ask(runner, session.id, text, tune.run_config(request_id, recent, timeout_ms))
            tune.LOG.append(f"  answer: {events[-1].content.parts[-1].text}")
    except Exception as exc:  # the failures are what this scenario records
        error = f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
        tune.LOG.append(f"  raised {error}")
    finally:
        await runner.close()
    return {"turns": [list(t) for t in turns], "log": list(tune.LOG), "model_turns": list(MODEL_TURNS), "error": error}


BASE = [("req-1", "How do I roll back production?", None, 60_000), ("req-2", "Which page covers CI tokens?", None, 60_000)]
SCENARIOS = {
    "tuned": BASE + [("req-3", "What was my first question?", 4, 60_000)],
    "cap_at_function_call": BASE + [("req-3", "What was my first question?", 3, 60_000)],
    "timeout": [("req-1", "How do I roll back production?", None, 1)],
}


def main() -> None:
    rec = {"model": tune.MODEL, **{name: asyncio.run(scenario(turns)) for name, turns in SCENARIOS.items()}}
    out = [f"$ python tune.py   # {tune.MODEL}", *rec["tuned"]["log"], "",
           "# the same session, capped at 3 events", *rec["cap_at_function_call"]["log"][-3:], "",
           "# a 1 ms model-call timeout", *rec["timeout"]["log"]]
    (HERE / "run-output.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    (HERE / "recorded-runs.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
