"""A code-review agent as a LangGraph StateGraph: the model calls tools until it can answer."""
import os
import sys

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from review_queue import UnknownPullRequest, get_ci_status, get_diff, list_open_prs

TOOLS = [list_open_prs, get_diff, get_ci_status]
SYSTEM = """You help a developer work through the team's code-review queue.
Use the tools to look up pull requests; never guess a diff or a CI result.
Answer in at most three sentences and name each pull request by its number."""


# Gemini by default; REVIEW_MODEL=gemma4:e2b runs the same graph on a local Ollama model.
MODEL = os.environ.get("REVIEW_MODEL", "gemini-3.8-flash")


def chat_model():
    if MODEL.startswith("gemini"):
        return ChatGoogleGenerativeAI(model=MODEL)  # reads GOOGLE_API_KEY from the environment
    return ChatOllama(model=MODEL, temperature=0, reasoning=False)


def build_graph(model=None, *, catch_unknown_pr=True):
    llm = (model or chat_model()).bind_tools(TOOLS)

    def agent(state: MessagesState) -> dict:
        return {"messages": [llm.invoke([SystemMessage(SYSTEM), *state["messages"]])]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    # ToolNode runs every tool call in the last AIMessage and returns one ToolMessage per call.
    # By default it re-raises errors raised inside a tool; this one becomes a ToolMessage instead.
    tools = ToolNode(TOOLS, handle_tool_errors=UnknownPullRequest) if catch_unknown_pr else ToolNode(TOOLS)
    graph.add_node("tools", tools)
    graph.add_edge(START, "agent")
    # tools_condition: "tools" if the last message has tool calls, otherwise END. This is the stop condition.
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Which open pull request has failing CI, and why?"
    result = build_graph().invoke({"messages": [HumanMessage(question)]}, {"recursion_limit": 12})
    print(result["messages"][-1].text)
