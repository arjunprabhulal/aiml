"""Offline tests for the approval step. A scripted chat model replaces Gemma, so no Ollama is needed."""
import subprocess
import sys
from itertools import count
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from pydantic import ValidationError

import graph
import review_queue

ids, threads = count(), count()


class ScriptedChat(GenericFakeChatModel):
    """Returns the scripted messages in order; tool binding is a no-op."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name, **args):
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"c{next(ids)}"}])


POST = call("post_review_comment", number=415, body="Update the timeout test.")


@pytest.fixture(autouse=True)
def empty_code_host(tmp_path, monkeypatch):
    monkeypatch.setattr(review_queue, "CODE_HOST_DB", str(tmp_path / "code_host.sqlite"))


def posted():
    return [{"number": p["number"], "body": p["body"]} for p in review_queue.posted()]


def start(script, **options):
    g = graph.build_graph(ScriptedChat(messages=iter(script)), InMemorySaver(), **options)
    config = {"configurable": {"thread_id": f"t{next(threads)}"}}
    return g, config, g.invoke({"messages": [HumanMessage("Review 415.")]}, config)


def test_a_comment_pauses_before_it_is_posted():
    g, config, result = start([POST])
    assert result["__interrupt__"][0].value == {"tool": "post_review_comment", "args": POST.tool_calls[0]["args"]}
    assert g.get_state(config).next == ("human_review",)
    assert review_queue.posted() == []


def test_read_only_tools_run_without_a_pause():
    g, config, result = start([call("get_diff", number=415), AIMessage("Raises the timeout.")])
    assert "__interrupt__" not in result and result["messages"][2].content.startswith("client/http.py")


def test_approve_posts_the_proposed_comment():
    g, config, _ = start([POST, AIMessage("Posted.")])
    graph.resume(g, config, {"action": "approve"})
    assert posted() == [{"number": 415, "body": "Update the timeout test."}]


def test_edit_posts_the_reviewers_text_and_replaces_the_proposal():
    g, config, _ = start([POST, AIMessage("Posted.")])
    result = graph.resume(g, config, {"action": "edit", "body": "Please keep 10s and make it configurable."})
    assert posted() == [{"number": 415, "body": "Please keep 10s and make it configurable."}]
    proposals = [m for m in result["messages"] if getattr(m, "tool_calls", None)]
    assert len(proposals) == 1 and proposals[0].tool_calls[0]["args"]["body"].startswith("Please keep")


def test_reject_posts_nothing_and_the_reply_comes_from_the_decision():
    g, config, _ = start([POST])  # no scripted reply: calling the model again would fail
    result = graph.resume(g, config, {"action": "reject", "reason": "duplicate of the bot's note"})
    assert review_queue.posted() == []
    assert result["messages"][-2].status == "error"
    assert result["messages"][-1].content == "Nothing was posted: the reviewer rejected the comment (duplicate of the bot's note)."


def test_misspelled_decision_is_refused_and_the_thread_still_waits():
    g, config, _ = start([POST, AIMessage("Posted.")])
    with pytest.raises(ValidationError):
        graph.resume(g, config, {"action": "approved"})
    assert g.get_state(config).next == ("human_review",) and review_queue.posted() == []
    graph.resume(g, config, {"action": "approve"})
    assert len(review_queue.posted()) == 1


def test_a_thread_without_a_pending_review_is_refused():
    g, config, _ = start([POST])
    with pytest.raises(LookupError):
        graph.resume(g, {"configurable": {"thread_id": "no-such-thread"}}, {"action": "approve"})


def test_resume_needs_a_checkpointer():
    g = graph.build_graph(ScriptedChat(messages=iter([POST])))
    assert "__interrupt__" in g.invoke({"messages": [HumanMessage("Review 415.")]})
    with pytest.raises(RuntimeError, match="without checkpointer"):
        g.invoke(Command(resume={"action": "approve"}))


def test_the_review_node_runs_again_from_the_top_on_resume(monkeypatch):
    calls = []
    real = graph.interrupt
    monkeypatch.setattr(graph, "interrupt", lambda value, **kw: calls.append(value) or real(value, **kw))
    g, config, _ = start([POST, AIMessage("Posted.")])
    graph.resume(g, config, {"action": "approve"})
    assert len(calls) == 2  # once when it paused, once more when it resumed
    assert len(review_queue.posted()) == 1  # the post runs in ToolNode, after the decision


def test_running_the_same_approved_call_twice_posts_once():
    only_tools = StateGraph(MessagesState)
    only_tools.add_node("tools", ToolNode([review_queue.post_review_comment]))
    only_tools.add_edge(START, "tools")
    tools = only_tools.compile()
    for _ in range(2):  # a retry after a crash replays the same tool call ID
        out = tools.invoke({"messages": [HumanMessage("Review 415."), POST]})
    out["messages"] = out["messages"][2:]
    assert len(review_queue.posted()) == 1 and out["messages"][0].content == "Already posted on #415."


# Runs in a fresh Python process: post the approved call through ToolNode, print the tool's reply, exit.
POST_IN_NEW_PROCESS = """
import sys
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
import review_queue
review_queue.CODE_HOST_DB = sys.argv[1]
call = AIMessage("", tool_calls=[{"name": "post_review_comment", "id": "call-415",
                                  "args": {"number": 415, "body": "Update the timeout test."}}])
graph = StateGraph(MessagesState)
graph.add_node("tools", ToolNode([review_queue.post_review_comment]))
graph.add_edge(START, "tools")
print(graph.compile().invoke({"messages": [HumanMessage("Review 415."), call]})["messages"][-1].content)
"""


def test_a_replay_after_a_restart_posts_nothing():
    replies = [subprocess.run([sys.executable, "-c", POST_IN_NEW_PROCESS, review_queue.CODE_HOST_DB],
                              capture_output=True, text=True, check=True, cwd=Path(__file__).parent).stdout.strip()
               for _ in range(2)]  # the process that posted is gone; a new one replays the same call
    assert replies == ["Posted comment 1 on #415.", "Already posted on #415."]
    assert posted() == [{"number": 415, "body": "Update the timeout test."}]
