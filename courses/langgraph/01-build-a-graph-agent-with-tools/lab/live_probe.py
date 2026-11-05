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
MAX_CALLS = 3
MAX_OUTPUT_TOKENS = 4096
QUESTION = ("For pull request #415, inspect its diff and CI status. In at most three sentences, "
            "explain why CI fails and which changed constant conflicts with the test. "
            "Use the supplied read-only tools; do not change files or CI.")
POLICY = {"lesson_id": "build-a-graph-agent-with-tools", "model": MODEL,
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
    expected = os.environ.get("LG_LIVE_SCOPE_SHA256", "")
    marker = getattr(sys, "_aiml_langgraph_guard_active", None)
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

    def bind_tools(self, tools, **kwargs):
        return GuardedModel(self.model.bind_tools(tools, **kwargs), calls=self.calls, events=self.events)

    def invoke(self, messages):
        if self.calls[0] >= MAX_CALLS:
            raise ProbeStopped("model_call_limit")
        self.calls[0] += 1
        self.events("model_request", ordinal=self.calls[0], policy=POLICY)
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
        for call in reply.tool_calls:
            if call["name"] == "list_open_prs" and call["args"] == {}:
                continue
            if call["name"] in {"get_diff", "get_ci_status"} and call["args"] == {"number": 415}:
                continue
            raise ProbeStopped("unexpected_tool_request")
        return reply


def run_probe(model, *, events: Callable = emit) -> dict:
    from langchain_core.messages import HumanMessage
    from graph import build_graph
    guarded = GuardedModel(model, events=events)
    graph = build_graph(guarded)
    state = None
    tool_names = set()
    for kind, update in graph.stream({"messages": [HumanMessage(QUESTION)]}, {"recursion_limit": 8},
                                     stream_mode=["updates", "values"]):
        if kind == "values":
            state = update
            continue
        for node, delta in update.items():
            events("graph_step", node=node,
                   messages=[public_message(m) for m in delta.get("messages", [])])
            if node == "tools":
                tool_names.update(m.name for m in delta["messages"] if m.status == "success")
    if state is None:
        raise ProbeStopped("incomplete_no_state")
    answer = state["messages"][-1].text
    if not {"get_diff", "get_ci_status"}.issubset(tool_names):
        raise ProbeStopped("incomplete_missing_required_tool_evidence")
    # These literal checks provide evidence for review, not a semantic correctness certificate.
    checks = {"names_pr": "415" in answer, "names_constant": "DEFAULT_TIMEOUT" in answer,
              "names_expected_value": "10" in answer, "names_changed_value": "30" in answer,
              "names_test": "test_default_timeout" in answer}
    result = {"status": "completed_requires_semantic_review" if all(checks.values()) else "incomplete_answer_contract",
              "model_calls": guarded.calls[0], "answer": answer, "literal_checks": checks,
              "tools": sorted(tool_names)}
    events("completion", **result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        approve_guard()
        emit("task", question=QUESTION, policy=POLICY)
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
