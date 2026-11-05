"""The code-review agent triages CI, with a timeout on every tool and model call and a token budget."""
import asyncio
import operator
import os
import sys
from typing import Annotated, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langgraph.errors import NodeError, NodeTimeoutError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, TimeoutPolicy
from typing_extensions import TypedDict

import ci

TOOLS = [ci.list_failed_jobs, ci.fetch_job_log]
SYSTEM = """You help a developer work through the team's code-review queue. To explain a CI failure,
list the pull request's failed jobs, fetch the log of each, and explain the failure in two sentences.
If a tool fails, say what you could not check."""
MODEL = os.environ.get("REVIEW_MODEL", "gemini-3.8-flash")  # REVIEW_MODEL=gemma4:e2b runs it on Ollama


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    tokens: Annotated[int, operator.add]  # sum of valid reported token counts
    usage_known: bool  # false when the latest reply has missing or invalid usage
    stop_reason: str


def tool_timed_out(error: TimeoutError) -> str:
    """Turn a tool timeout into a tool message, so the model can answer without it."""
    return (f"The tool call did not finish within {ci.TOOL_TIMEOUT:g}s, so its result is unknown. "
            "This says nothing about the CI job itself. Do not retry.")


def model_failed(state: State, error: NodeError) -> Command:
    """The model node timed out (or raised): end the run in a named state instead of an exception."""
    return Command(update={"usage_known": False, "stop_reason": "model_timeout" if isinstance(error.error, NodeTimeoutError) else "model_error",
                           "messages": [AIMessage(f"Stopped: {error.error}")]}, goto=END)


def chat_model():
    if MODEL.startswith("gemini"):
        return ChatGoogleGenerativeAI(model=MODEL, max_retries=1)  # one client retry inside the node timeout
    return ChatOllama(model=MODEL, temperature=0, reasoning=False)


def build_graph(model=None, *, token_budget=4000, model_timeout=60.0):
    llm = (model or chat_model()).bind_tools(TOOLS)

    async def agent(state: State) -> dict:
        reply = await llm.ainvoke([SystemMessage(SYSTEM), *state["messages"]])
        usage = reply.usage_metadata
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        known = isinstance(total, int) and not isinstance(total, bool) and total >= 0
        update = {"messages": [reply], "usage_known": known}
        if known:
            update["tokens"] = total
        return update

    def route(state: State) -> Literal["tools", "stop", "__end__"]:
        if not state["usage_known"]:
            return "stop"
        if not state["messages"][-1].tool_calls:
            return END
        return "stop" if state["tokens"] >= token_budget else "tools"

    def stop(state: State) -> dict:
        used = state["tokens"]
        if not state["usage_known"]:
            return {"stop_reason": "missing_usage", "messages": [AIMessage(
                f"Stopped: model usage is missing or invalid; the run total is unknown. "
                f"The known subtotal from reported calls is {used} tokens.")]}
        return {"stop_reason": "token_budget",
                "messages": [AIMessage(f"Stopped: {used} of {token_budget} tokens used.")]}

    graph = StateGraph(State)
    graph.add_node("agent", agent, timeout=TimeoutPolicy(run_timeout=model_timeout), error_handler=model_failed)
    graph.add_node("tools", ToolNode(TOOLS, handle_tool_errors=tool_timed_out))
    graph.add_node("stop", stop)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route)
    graph.add_edge("tools", "agent")
    graph.add_edge("stop", END)
    return graph.compile()


async def triage(graph, question: str) -> dict:
    return await graph.ainvoke({"messages": [HumanMessage(question)], "tokens": 0}, {"recursion_limit": 12})


if __name__ == "__main__":
    result = asyncio.run(triage(build_graph(), " ".join(sys.argv[1:]) or "Why is CI failing on pull request 415?"))
    label = "tokens" if result.get("usage_known", False) else "known subtotal; run total unknown"
    print(result.get("stop_reason", "answered"), result["tokens"], label, "|", result["messages"][-1].text)
