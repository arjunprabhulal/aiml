"""The review team files a tracker ticket for a failed CI job. The write step retries, and an idempotency key stops duplicates."""
import os
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# The default retry_on retries ConnectionError but no other OSError, including TimeoutError, so name it.
MODEL = os.environ.get("REVIEW_MODEL", "gemini-3.8-flash")  # REVIEW_MODEL=gemma4:e2b runs it on Ollama
RETRY = RetryPolicy(max_attempts=3, initial_interval=0.5, retry_on=(ConnectionError, TimeoutError))


class Ticket(BaseModel):
    title: str = Field(description="Under 70 characters: what failed and where.")
    labels: list[Literal["bug", "flaky-test", "infra", "dependencies"]]


class State(TypedDict, total=False):
    log: str
    ticket: dict
    filed: dict


def stable_key(config: RunnableConfig) -> str:
    """Same thread, same step: the same key on every retry and every resume."""
    return f"{config['configurable']['thread_id']}:file_ticket"


def chat_model():
    if MODEL.startswith("gemini"):
        return ChatGoogleGenerativeAI(model=MODEL)  # reads GOOGLE_API_KEY from the environment
    return ChatOllama(model=MODEL, temperature=0, reasoning=False)


def build_graph(tracker, drafter=None, retry=RETRY, key=stable_key, checkpointer=None):
    drafter = drafter or chat_model().with_structured_output(Ticket)

    def draft(state: State) -> dict:
        ticket = drafter.invoke(f"Write a tracker ticket for this failed CI job:\n{state['log']}")
        return {"ticket": ticket.model_dump()}

    def file_ticket(state: State, config: RunnableConfig) -> dict:
        return {"filed": tracker.create(**state["ticket"], idempotency_key=key(config) if key else None)}

    graph = StateGraph(State)
    graph.add_node("draft", draft)  # the model call is its own step, so a retry below never repeats it
    graph.add_node("file_ticket", file_ticket, retry_policy=retry)
    graph.add_edge(START, "draft")
    graph.add_edge("draft", "file_ticket")
    graph.add_edge("file_ticket", END)
    return graph.compile(checkpointer=checkpointer)
