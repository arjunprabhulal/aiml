"""Bounded genuine-model probe; refuses unless an external guard approves first.

This probe does not authorize provider spending. Its model-call limit supplements,
but does not replace, the coordinator's HTTP-attempt and token guard.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Callable

MODEL = "gemini-3.8-flash"
MAX_CALLS = 10
MAX_OUTPUT_TOKENS = 4096
DECISION = "mlee reviews #412, and it must merge before the 2.5 freeze on November 14."
LOG = "\n".join(f"09:14:{n:02d} tests/test_client.py::test_retry_{n} PASSED" for n in range(15))
TURNS = [
    "For #415 keep DEFAULT_TIMEOUT at 10s and add a per-client timeout override instead. Acknowledge briefly.",
    DECISION + " Acknowledge briefly.",
    "Here is the CI retry log for #415. Summarize what it shows in one sentence.\n" + LOG,
    "Draft a one-line review comment asking for a per-client timeout override. "
    "The proposed API accepts an optional timeout_seconds argument on the client constructor; "
    "when absent, it keeps the existing default. Ask for a regression test that covers both omitted "
    "and explicit values. Keep backward compatibility for existing callers. Do not claim the code "
    "was changed or tests were executed. The supplied test log is a fixture for discussion, not a "
    "fresh CI result. Keep the comment about the timeout API only; do not discuss reviewers or deadlines.",
    "Who reviews #412, and when must it merge?",
]
QUESTION = "Run the same five-turn review conversation in independent plain and pinned threads."
POLICY = {"lesson_id": "langgraph-context-budget", "model": MODEL,
          "max_model_calls": MAX_CALLS, "max_output_tokens": MAX_OUTPUT_TOKENS,
          "thinking_level": "low", "timeout_seconds": 45, "max_retries": 0,
          "vertexai": False}


class ProbeStopped(RuntimeError):
    """A named incomplete result; never an acceptable model answer."""


def emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def public_message(message) -> dict:
    """Readable public receipt; opaque provider fields stay in private transport logs."""
    result = {"type": message.type, "text": message.text}
    if message.type == "ai":
        result.update(tool_calls=[{"name": c["name"], "args": c["args"], "id": c["id"]}
                                  for c in message.tool_calls],
                      usage=message.usage_metadata,
                      finish_reason=message.response_metadata.get("finish_reason"))
    elif message.type == "tool":
        result.update(name=message.name, tool_call_id=message.tool_call_id, status=message.status)
    return result


def approve_guard() -> str:
    """Require the in-process external guard handshake before SDK/key access."""
    expected = os.environ.get("LG_LIVE_03_SCOPE_SHA256", "")
    marker = getattr(sys, "_aiml_langgraph_03_guard_active", None)
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ProbeStopped("external_guard_required")
    if marker != expected:
        raise ProbeStopped("external_guard_scope_mismatch")
    return expected


def make_model():
    # Imported and constructed only after approve_guard succeeds in main().
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model=MODEL, thinking_level="low", max_output_tokens=MAX_OUTPUT_TOKENS,
                                 max_retries=0, timeout=45, vertexai=False)


class GuardedModel:
    def __init__(self, model, *, calls=None, events: Callable = emit):
        self.model = model
        self.calls = calls if calls is not None else [0]
        self.events = events
        self.views = []

    def bind_tools(self, tools, **kwargs):
        return GuardedModel(self.model.bind_tools(tools, **kwargs), calls=self.calls, events=self.events)

    def invoke(self, messages):
        if self.calls[0] >= MAX_CALLS:
            raise ProbeStopped("model_call_limit")
        self.calls[0] += 1
        self.views.append(messages)
        self.events("model_request", ordinal=self.calls[0], policy=POLICY,
                    sent_view=[{"role": m.type, "text": m.text} for m in messages])
        reply = self.model.invoke(messages)
        self.events("model_response", ordinal=self.calls[0], message=public_message(reply))
        reason = reply.response_metadata.get("finish_reason")
        if reason == "MAX_TOKENS":
            raise ProbeStopped("incomplete_max_tokens")
        if reason != "STOP":
            raise ProbeStopped("incomplete_finish_reason")
        if not reply.tool_calls and not reply.text.strip():
            raise ProbeStopped("incomplete_empty_answer")
        usage = reply.usage_metadata
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise ProbeStopped("incomplete_unknown_usage")
        if reply.tool_calls:
            raise ProbeStopped("unexpected_tool_request")
        return reply


def run_probe(model, *, events: Callable = emit) -> dict:
    from langchain_core.messages import HumanMessage
    from graph import BUDGET, build_graph
    guarded = GuardedModel(model, events=events)
    graph = build_graph(guarded)
    threads = []
    for name, pin in [("plain", False), ("pinned", True)]:
        config = {"configurable": {"thread_id": "live-probe-" + name}}
        turns, state = [], None
        for ordinal, question in enumerate(TURNS, 1):
            events("turn_input", thread=name, turn=ordinal, question=question, pin=pin and ordinal == 2)
            update = {"messages": [HumanMessage(question)]}
            if pin and ordinal == 2:
                update["pinned"] = [DECISION]
            state = graph.invoke(update, config)
            observation = {"turn": ordinal, **state["view"], "reply": state["messages"][-1].text}
            turns.append(observation)
            events("turn_result", thread=name, **observation)
        last_view = guarded.views[-1]
        thread = {"thread": name, "stored_messages": len(state["messages"]),
                  "last_view_has_decision": any(DECISION in m.text for m in last_view),
                  "system_has_pinned_decision": DECISION in last_view[0].text,
                  "turns": turns}
        threads.append(thread)
    plain, pinned = threads
    checks = {"stored_both_threads": all(t["stored_messages"] == 10 for t in threads),
              "plain_decision_trimmed": not plain["last_view_has_decision"],
              "pinned_system_retains_decision": pinned["system_has_pinned_decision"],
              "plain_answer_does_not_name_mlee": "mlee" not in plain["turns"][-1]["reply"].lower(),
              "pinned_answer_names_mlee": "mlee" in pinned["turns"][-1]["reply"].lower(),
              "pinned_answer_names_date": "november 14" in pinned["turns"][-1]["reply"].lower()}
    result = {"status": "completed_requires_semantic_review" if all(checks.values()) else "incomplete_comparison_not_observed",
              "model_calls": guarded.calls[0], "approximate_input_budget": BUDGET,
              "checks": checks, "threads": threads,
              "boundary": "Approximate trimming is not a provider token cap. Generated replies require semantic review; reading is not mastery."}
    events("completion", **result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        approve_guard()
        emit("task", question=QUESTION, turns=TURNS, pinned_decision=DECISION, policy=POLICY)
        result = run_probe(make_model())
        return 0 if result["status"] == "completed_requires_semantic_review" else 2
    except ProbeStopped as error:
        emit("completion", status="incomplete", reason=str(error))
        return 2
    except Exception as error:
        # Do not print provider exception strings: those may include request secrets.
        emit("completion", status="failed", error_type=type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
