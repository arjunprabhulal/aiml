"""A code-review agent that pauses for a human decision before it posts a review comment."""
import os
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from review_queue import get_ci_status, get_diff, post_review_comment

TOOLS = [get_diff, get_ci_status, post_review_comment]
NEEDS_APPROVAL = {"post_review_comment"}  # tools that change something other people see
SYSTEM = """You review pull requests for the team. Read the diff and the CI result with the tools,
then post exactly one review comment with post_review_comment. Keep the comment under 40 words.
After that, tell the developer in one sentence what you posted."""


# Gemini by default; REVIEW_MODEL=gemma4:e2b runs the same graph on a local Ollama model.
MODEL = os.environ.get("REVIEW_MODEL", "gemini-3.8-flash")


def chat_model():
    if MODEL.startswith("gemini"):
        return ChatGoogleGenerativeAI(model=MODEL)  # reads GOOGLE_API_KEY from the environment
    return ChatOllama(model=MODEL, temperature=0, reasoning=False)


class Decision(BaseModel):
    """What the human reviewer sends back to resume the run."""
    action: Literal["approve", "edit", "reject"]
    body: str | None = None    # the replacement comment, for "edit"
    reason: str | None = None  # why, for "reject"


def build_graph(model=None, checkpointer=None, *, model_replies_to_rejection=False):
    llm = (model or chat_model()).bind_tools(TOOLS)

    def agent(state: MessagesState) -> dict:
        return {"messages": [llm.invoke([SystemMessage(SYSTEM), *state["messages"]])]}

    def route(state: MessagesState) -> Literal["human_review", "tools", "__end__"]:
        calls = state["messages"][-1].tool_calls
        if not calls:
            return END
        return "human_review" if any(c["name"] in NEEDS_APPROVAL for c in calls) else "tools"

    def human_review(state: MessagesState) -> Command[Literal["tools", "agent", "__end__"]]:
        # This node runs again from the top on resume: nothing before interrupt() may have side effects.
        message: AIMessage = state["messages"][-1]
        calls, rejected = [], None
        for call in message.tool_calls:
            if call["name"] in NEEDS_APPROVAL:
                decision = interrupt({"tool": call["name"], "args": call["args"]}, response_schema=Decision)
                if decision.action == "edit":
                    call = {**call, "args": {**call["args"], "body": decision.body}}
                elif decision.action == "reject":
                    rejected = decision.reason or "no reason given"
            calls.append(call)
        if rejected:  # run nothing from this step, and answer every call
            not_run = [ToolMessage(f"Not run: the reviewer rejected the comment ({rejected}).",
                                   tool_call_id=c["id"], name=c["name"], status="error") for c in calls]
            if model_replies_to_rejection:
                return Command(goto="agent", update={"messages": not_run})
            # The reply comes from the decision, not from the model, so it cannot claim a post.
            return Command(goto=END, update={"messages": [
                *not_run, AIMessage(f"Nothing was posted: the reviewer rejected the comment ({rejected}).")]})
        # Same message ID, so the add_messages reducer replaces the message instead of appending it.
        return Command(goto="tools", update={"messages": [message.model_copy(update={"tool_calls": calls})]})

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("human_review", human_review)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)


def resume(graph, config: dict, decision: dict) -> dict:
    """Resume a paused thread. Refuse a thread that is not waiting, instead of starting a new run."""
    if not graph.get_state(config).interrupts:
        raise LookupError(f"Thread {config['configurable']['thread_id']!r} has no pending review.")
    return graph.invoke(Command(resume=decision), config)
