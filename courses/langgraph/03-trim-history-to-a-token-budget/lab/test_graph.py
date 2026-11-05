"""Offline tests: a scripted chat model replaces Gemini; the recorded Gemini run is checked as a fixture."""
import itertools
import json
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.messages.utils import count_tokens_approximately

from graph import BUDGET, ContextTooLarge, build_graph, count_tokens

RUN = json.loads(Path(__file__).with_name("runs.json").read_text())
FILLER = "We went through the sync design again. " * 12


class Scripted(GenericFakeChatModel):
    seen: list = []

    def invoke(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super().invoke(messages, *args, **kwargs)


def chat(turns, pin=None):
    model = Scripted(messages=(AIMessage(f"Noted {i}.") for i in itertools.count()), seen=[])
    graph = build_graph(model)
    config = {"configurable": {"thread_id": "t"}}
    for i, text in enumerate(turns):
        update = {"messages": [HumanMessage(text)]}
        if pin and i == 0:
            update["pinned"] = [pin]
        state = graph.invoke(update, config)
    return state, model.seen[-1]


def test_the_thread_keeps_every_message_while_the_model_sees_a_trimmed_view():
    state, view = chat([f"Decision {i}. {FILLER}" for i in range(6)])
    assert len(state["messages"]) == 12
    assert state["view"]["sent"] < 12
    assert count_tokens(view) <= BUDGET


def test_the_view_starts_on_a_user_turn():
    _, view = chat([f"Decision {i}. {FILLER}" for i in range(6)])
    assert isinstance(view[1], HumanMessage)


def test_a_trimmed_decision_is_gone_from_the_view():
    _, view = chat(["mlee reviews #412.", *[f"Note {i}. {FILLER}" for i in range(4)], "Who reviews #412?"])
    assert not any("mlee" in m.text for m in view)


def test_a_pinned_decision_survives_trimming():
    _, view = chat(["mlee reviews #412.", *[f"Note {i}. {FILLER}" for i in range(4)], "Who reviews #412?"],
                   pin="mlee reviews #412.")
    assert "mlee reviews #412." in view[0].text


def test_the_counter_adds_the_reasoning_tokens_a_reply_carries_back():
    reply = AIMessage("Noted.", usage_metadata={"input_tokens": 9, "output_tokens": 230, "total_tokens": 239,
                                                "output_token_details": {"reasoning": 220}})
    assert count_tokens([reply]) == count_tokens_approximately([reply]) + 220


def test_a_question_larger_than_the_budget_is_refused_before_the_model_call():
    model = Scripted(messages=iter([AIMessage("never")]), seen=[])
    with pytest.raises(ContextTooLarge):
        build_graph(model).invoke({"messages": [HumanMessage("log line 09:15:01 ok " * 200)]},
                                  {"configurable": {"thread_id": "big"}})
    assert model.seen == []


def test_recorded_run_pinning_kept_the_answer():
    plain, pinned = RUN["runs"]
    assert "do not have" in plain["turns"][-1]["reply"]
    assert "mlee" in pinned["turns"][-1]["reply"]


def test_recorded_run_chars_only_estimate_missed_the_signatures():
    last = RUN["runs"][0]["turns"][-1]  # three messages sent, one of them a Gemini reply
    assert last["chars_only_estimate"] < last["server_tokens"] / 2 < last["estimated_tokens"]


def test_recorded_log_turn_was_billed_above_the_budget():
    log_turn = RUN["runs"][0]["turns"][2]
    assert log_turn["estimated_tokens"] <= RUN["budget"] < log_turn["server_tokens"]
