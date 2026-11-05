"""A code-review agent that keeps each repository's review conventions in a LangGraph store."""
import os
import uuid
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, ToolRuntime, tools_condition
from langgraph.runtime import Runtime

from review_queue import get_diff

Topic = Literal["line_length", "tests", "logging", "dependencies"]
SYSTEM = """You review pull requests in the repository {repo}. Use get_diff to read a pull request.
Call remember_convention only when the developer's latest message states a rule for this repository,
then confirm in one sentence. Judge pull requests only against the saved conventions below,
and answer in at most two sentences.
Saved conventions for {repo}:
{conventions}"""


# Gemini by default; REVIEW_MODEL=gemma4:e2b runs the same graph on a local Ollama model.
MODEL = os.environ.get("REVIEW_MODEL", "gemini-3.8-flash")


def chat_model():
    if MODEL.startswith("gemini"):
        return ChatGoogleGenerativeAI(model=MODEL)  # reads GOOGLE_API_KEY from the environment
    return ChatOllama(model=MODEL, temperature=0, reasoning=False)


@dataclass
class ReviewContext:
    repo: str  # set by the caller for each run, never by the model


def namespace(repo: str) -> tuple[str, ...]:
    return ("conventions", repo)


def make_remember(key_by_topic: bool):
    @tool
    def remember_convention(topic: Topic, quote: str, runtime: ToolRuntime[ReviewContext]) -> str:
        """Save a review rule the developer just stated for this repository.
        quote: the developer's words that state the rule, copied exactly. These words are saved as the rule."""
        said = next(m.content for m in reversed(runtime.state["messages"]) if isinstance(m, HumanMessage))
        start = said.lower().find(quote.strip().lower()) if quote.strip() else -1
        if start < 0:
            return "Not saved: the quote is not in the developer's latest message."
        # The rule is the developer's own words, cut from their message: the model cannot add its own wording.
        rule = said[start:start + len(quote.strip())]
        # Keyed by topic, a new rule replaces the old one. A fresh ID per write keeps both.
        key = topic if key_by_topic else str(uuid.uuid4())
        value = {"topic": topic, "rule": rule, "thread": runtime.config["configurable"]["thread_id"]}
        runtime.store.put(namespace(runtime.context.repo), key, value)
        return f"Saved the {topic} rule for {runtime.context.repo}."
    return remember_convention


def recall(store, repo: str) -> str:
    items = sorted(store.search(namespace(repo), limit=50), key=lambda item: item.updated_at)
    return "\n".join(f"- {item.value['topic']}: {item.value['rule']}" for item in items) or "- none saved"


def build_graph(store, model=None, *, checkpointer=None, key_by_topic=True):
    tools = [get_diff, make_remember(key_by_topic)]
    llm = (model or chat_model()).bind_tools(tools)

    def agent(state: MessagesState, runtime: Runtime[ReviewContext]) -> dict:
        repo = runtime.context.repo
        system = SYSTEM.format(repo=repo, conventions=recall(runtime.store, repo))
        return {"messages": [llm.invoke([SystemMessage(system), *state["messages"]])]}

    graph = StateGraph(MessagesState, context_schema=ReviewContext)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    # The checkpointer keeps each thread's messages; the store keeps conventions across threads.
    return graph.compile(checkpointer=checkpointer, store=store)
