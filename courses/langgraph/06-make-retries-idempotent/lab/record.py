"""Run each retry and key choice against a tracker that loses one response, with Gemini drafting the ticket."""
import json
import uuid

from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import RetryPolicy

from tracker import Tracker
from workflow import MODEL, RETRY, Ticket, build_graph, chat_model, stable_key

LOG = """job unit-tests #812 on pull request 415 (Raise the default HTTP timeout to 30s)
FAILED tests/test_client.py::test_default_timeout - AssertionError: expected 10, got 30
1 failed, 214 passed in 38.2s"""
SCENARIOS = {  # name: (retry policy, key function)
    "default policy": (RetryPolicy(), None),
    "retry, no key": (RETRY, None),
    "retry, key per attempt": (RETRY, lambda config: str(uuid.uuid4())),
    "retry, stable key": (RETRY, stable_key),
}


def main() -> None:
    model = chat_model().with_structured_output(Ticket)
    runs = []
    for name, (retry, key) in SCENARIOS.items():
        tracker, calls = Tracker(lost_responses=1), []
        drafter = RunnableLambda(lambda prompt: calls.append(1) or model.invoke(prompt))
        graph = build_graph(tracker, drafter, retry, key)
        try:
            result = graph.invoke({"log": LOG}, {"configurable": {"thread_id": "ci-812"}})
            outcome = {"filed": result["filed"]}
        except TimeoutError as error:
            outcome = {"error": f"TimeoutError: {error}"}
        runs.append({"scenario": name, **outcome, "create_requests": len(tracker.requests),
                     "tickets": tracker.tickets, "model_calls": len(calls)})

    # No retries left: the run fails after the ticket was created. Resume the thread from its checkpoint.
    tracker, calls = Tracker(lost_responses=1), []
    drafter = RunnableLambda(lambda prompt: calls.append(1) or model.invoke(prompt))
    graph = build_graph(tracker, drafter, RetryPolicy(max_attempts=1), stable_key, InMemorySaver())
    config = {"configurable": {"thread_id": "ci-812"}}
    try:
        graph.invoke({"log": LOG}, config)
    except TimeoutError as error:
        first = f"TimeoutError: {error}"
    result = graph.invoke(None, config)
    runs.append({"scenario": "fail, then resume with a stable key", "error": first, "filed": result["filed"],
                 "create_requests": len(tracker.requests), "tickets": tracker.tickets, "model_calls": len(calls)})

    with open("runs.json", "w") as f:
        json.dump({"model": MODEL, "log": LOG, "runs": runs}, f, indent=1)
    for r in runs:
        print(f"== {r['scenario']}")
        print(f"  model calls {r['model_calls']}, create requests {r['create_requests']}, tickets {len(r['tickets'])}")
        print("  " + (f"error:  {r['error']}" if "filed" not in r else f"filed:  {json.dumps(r['filed'])}"))
        if "filed" in r and "error" in r:
            print(f"  first run failed with {r['error']}")


if __name__ == "__main__":
    main()
