"""A code-review chat graph. The checkpointer keeps the whole thread; the model sees a trimmed view."""
import operator
import os
import sys
from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

BUDGET = 400  # approximate tokens the model may see per turn: instructions, pinned notes, history, question
SYSTEM = """You help a developer work through the team's code-review queue. Answer in at most three
sentences, from the conversation and the pinned decisions only. If a fact is in neither, say you do not have it."""
MODEL = os.environ.get("REVIEW_MODEL", "gemini-3.8-flash")  # REVIEW_MODEL=gemma4:e2b runs it on Ollama


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]  # the whole thread; new IDs append, matching IDs replace
    pinned: Annotated[list[str], operator.add]  # decisions the app pins; never trimmed
    view: dict  # what the model saw this turn, for the recording


class ContextTooLarge(ValueError):
    pass


def count_tokens(messages: list[AnyMessage]) -> int:
    """Heuristic: character estimate plus prior reasoning usage, calibrated against these saved Gemini calls."""
    return count_tokens_approximately(messages) + sum(
        ((m.usage_metadata or {}).get("output_token_details") or {}).get("reasoning", 0)
        for m in messages if isinstance(m, AIMessage))


def model_view(state: State, budget: int = BUDGET) -> list[AnyMessage]:
    notes = "".join(f"\n- {note}" for note in state.get("pinned", []))
    system = SystemMessage(SYSTEM + (f"\n\nPinned decisions:{notes}" if notes else ""))
    room = budget - count_tokens([system])
    history = trim_messages(state["messages"], max_tokens=room, strategy="last",
                            token_counter=count_tokens, start_on="human", end_on="human")
    if not history:  # even the question alone does not fit
        raise ContextTooLarge(f"the question needs more than the {room} tokens left after the instructions")
    return [system, *history]


def chat_model():
    if MODEL.startswith("gemini"):
        return ChatGoogleGenerativeAI(model=MODEL)  # reads GOOGLE_API_KEY from the environment
    return ChatOllama(model=MODEL, temperature=0, reasoning=False)


def build_graph(model=None, budget: int = BUDGET, checkpointer=None):
    model = model or chat_model()

    def respond(state: State) -> dict:
        view = model_view(state, budget)
        reply = model.invoke(view)
        return {"messages": [reply], "view": {
            "sent": len(view) - 1, "stored": len(state["messages"]),
            "estimated_tokens": count_tokens(view), "chars_only_estimate": count_tokens_approximately(view),
            "server_tokens": (reply.usage_metadata or {}).get("input_tokens")}}

    builder = StateGraph(State)
    builder.add_node("respond", respond)
    builder.add_edge(START, "respond")
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


if __name__ == "__main__":
    graph = build_graph()
    config = {"configurable": {"thread_id": "cli"}}
    for line in sys.stdin:
        state = graph.invoke({"messages": [HumanMessage(line.strip())]}, config)
        print(state["view"], "|", state["messages"][-1].text)
