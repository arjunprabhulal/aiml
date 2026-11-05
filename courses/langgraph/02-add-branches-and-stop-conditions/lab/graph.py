"""The code-review agent with its own router: it branches on each reply and stops inside a step limit."""
import json
import os
import sys
from typing import Annotated, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.managed import RemainingSteps
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from review_queue import UnknownPullRequest, get_ci_status, get_diff, list_open_prs

TOOLS = [list_open_prs, get_diff, get_ci_status]
RECURSION_LIMIT = 12  # graph steps per run; each node run is one step
SYSTEM = """You help a developer work through the team's code-review queue.
Use the tools to look up pull requests; never guess a diff or a CI result.
Answer in at most three sentences and name each pull request by its number."""
MODEL = os.environ.get("REVIEW_MODEL", "gemini-3.8-flash")  # REVIEW_MODEL=gemma4:e2b runs it on Ollama


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    remaining_steps: RemainingSteps  # filled in by LangGraph: limit minus steps taken
    stop_reason: str


def stop_reason(state: State) -> str | None:
    """Why the run must stop now, or None if it may continue."""
    *earlier, last = state["messages"]
    # Exact match on name and arguments; sort_keys so {"a": 1, "b": 2} and {"b": 2, "a": 1} are one call.
    # A call that asks for the same thing in other words, such as "415" for 415, is not caught.
    def same(c): return c["name"], json.dumps(c["args"], sort_keys=True)
    seen = {same(c) for m in earlier if isinstance(m, AIMessage) for c in m.tool_calls}
    if any(same(c) in seen for c in last.tool_calls):
        return "repeated_call"
    # Calling tools needs room for three more steps: tools, agent, and a possible stop.
    if last.tool_calls and state["remaining_steps"] < 4:
        return "step_limit"
    return None


def chat_model():
    if MODEL.startswith("gemini"):
        return ChatGoogleGenerativeAI(model=MODEL)  # reads GOOGLE_API_KEY from the environment
    return ChatOllama(model=MODEL, temperature=0, reasoning=False)


def build_graph(model=None):
    llm = (model or chat_model()).bind_tools(TOOLS)

    def agent(state: State) -> dict:
        return {"messages": [llm.invoke([SystemMessage(SYSTEM), *state["messages"]])]}

    def route(state: State) -> Literal["tools", "stop", "__end__"]:
        if stop_reason(state):
            return "stop"
        return "tools" if state["messages"][-1].tool_calls else END

    def stop(state: State) -> dict:
        reason = stop_reason(state)
        return {"stop_reason": reason, "messages": [AIMessage(f"I stopped before answering ({reason}).")]}

    graph = StateGraph(State)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS, handle_tool_errors=UnknownPullRequest))
    graph.add_node("stop", stop)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route)
    graph.add_edge("tools", "agent")
    graph.add_edge("stop", END)
    return graph.compile()


def ask(graph, question: str) -> dict:
    return graph.invoke({"messages": [HumanMessage(question)]}, {"recursion_limit": RECURSION_LIMIT})


if __name__ == "__main__":
    result = ask(build_graph(), " ".join(sys.argv[1:]) or "Which open pull request has failing CI, and why?")
    print(result.get("stop_reason", "answered"), "|", result["messages"][-1].text)
