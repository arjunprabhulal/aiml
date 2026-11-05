"""Offline tests: a fixed drafter replaces Gemini; the stub tracker loses responses on demand."""
import json
import uuid
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import RetryPolicy, default_retry_on

from tracker import Tracker
from workflow import RETRY, Ticket, build_graph, stable_key

RUN = json.loads(Path(__file__).with_name("runs.json").read_text())
FAST = RetryPolicy(max_attempts=3, initial_interval=0.01, retry_on=(ConnectionError, TimeoutError))
CONFIG = {"configurable": {"thread_id": "ci-812"}}


def drafter(calls):
    return RunnableLambda(lambda prompt: calls.append(prompt) or Ticket(title="test_default_timeout fails on #415", labels=["bug"]))


def file(tracker, retry=FAST, key=stable_key, calls=None):
    return build_graph(tracker, drafter([] if calls is None else calls), retry, key).invoke({"log": "FAILED"}, CONFIG)


def test_the_default_policy_does_not_retry_a_timeout():
    tracker = Tracker(lost_responses=1)
    with pytest.raises(TimeoutError):
        file(tracker, retry=RetryPolicy(initial_interval=0.01))
    assert len(tracker.requests) == 1 and len(tracker.tickets) == 1  # it failed, yet the ticket exists


def test_a_retry_without_a_key_files_a_duplicate():
    tracker = Tracker(lost_responses=1)
    file(tracker, key=None)
    assert [t["id"] for t in tracker.tickets] == ["REV-101", "REV-102"]


def test_a_key_made_per_attempt_does_not_stop_the_duplicate():
    tracker = Tracker(lost_responses=1)
    file(tracker, key=lambda config: str(uuid.uuid4()))
    assert len(tracker.tickets) == 2


def test_a_stable_key_turns_the_retry_into_a_replay():
    tracker, calls = Tracker(lost_responses=1), []
    filed = file(tracker, calls=calls)["filed"]
    assert filed == {"id": "REV-101", "title": "test_default_timeout fails on #415", "labels": ["bug"], "replayed": True}
    assert len(tracker.tickets) == 1 and len(calls) == 1  # the model step did not run again


def test_retries_stop_at_max_attempts():
    tracker = Tracker(lost_responses=5)
    with pytest.raises(TimeoutError):
        file(tracker, key=None)
    assert len(tracker.requests) == FAST.max_attempts


def test_a_resumed_thread_reuses_the_key_and_skips_the_model():
    tracker, calls = Tracker(lost_responses=1), []
    graph = build_graph(tracker, drafter(calls), RetryPolicy(max_attempts=1), stable_key, InMemorySaver())
    with pytest.raises(TimeoutError):
        graph.invoke({"log": "FAILED"}, CONFIG)
    assert graph.invoke(None, CONFIG)["filed"]["replayed"] is True
    assert len(tracker.tickets) == 1 and len(calls) == 1


def test_the_default_policy_retries_connection_error_but_no_other_os_error():
    assert issubclass(ConnectionError, OSError) and issubclass(TimeoutError, OSError)
    assert default_retry_on(ConnectionError()) and default_retry_on(ConnectionResetError())
    assert not default_retry_on(TimeoutError()) and not default_retry_on(FileNotFoundError())
    assert not default_retry_on(ValueError()) and not default_retry_on(TypeError())


def test_the_lesson_policy_names_timeout_error():
    assert RETRY.retry_on == (ConnectionError, TimeoutError)


def test_recorded_runs_match_the_lesson():
    by = {r["scenario"]: r for r in RUN["runs"]}
    assert "error" in by["default policy"] and len(by["default policy"]["tickets"]) == 1
    assert len(by["retry, no key"]["tickets"]) == 2 and len(by["retry, key per attempt"]["tickets"]) == 2
    assert len(by["retry, stable key"]["tickets"]) == 1 and by["retry, stable key"]["filed"]["replayed"]
