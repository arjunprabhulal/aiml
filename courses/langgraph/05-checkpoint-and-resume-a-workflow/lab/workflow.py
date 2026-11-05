"""The review team's release-notes workflow. Its state is checkpointed to SQLite after every step, so a crashed run resumes."""
import argparse
import json
import os
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

HERE = Path(__file__).parent
OUT = HERE / "out"
MODEL = os.environ.get("REVIEW_MODEL", "gemini-3.8-flash")  # REVIEW_MODEL=gemma4:e2b runs it on Ollama


class State(TypedDict, total=False):
    version: str
    prs: list[dict]
    notes: str
    path: str


def crash_point(node: str) -> None:
    """Kill the process at a named point, the way an OOM kill or a redeploy would."""
    if os.environ.get("CRASH_AT") == node:
        print(f"!! process killed in {node}", flush=True)
        os._exit(1)


def chat_model():
    if MODEL.startswith("gemini"):
        return ChatGoogleGenerativeAI(model=MODEL, max_output_tokens=1024, max_retries=0, timeout=30)
    return ChatOllama(model=MODEL, temperature=0, reasoning=False)


def build_graph(checkpointer, model=None):
    def collect(state: State) -> dict:
        prs = json.loads((HERE / "prs.json").read_text())
        return {"prs": [pr for pr in prs if "dependencies" not in pr["labels"]]}

    def summarize(state: State) -> dict:
        lines = "\n".join(f"#{pr['number']} {pr['title']}" for pr in state["prs"])
        reply = (model or chat_model()).invoke(
            f"Write release notes for version {state['version']}: one Markdown bullet per merged pull request, "
            f"user-facing wording, keep the #number.\n{lines}")
        return {"notes": reply.text}

    def write_file(state: State) -> dict:
        path = OUT / f"{state['version']}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"# Release {state['version']}\n\n{state['notes']}\n")
        return {"path": f"{OUT.name}/{path.name}"}

    def announce(state: State) -> dict:
        with open(OUT / "announcements.log", "a") as log:  # stands in for a chat or email post
            log.write(f"Released {state['version']}: {state['path']}\n")
        crash_point("announce")  # dies after the post, before LangGraph saves this step
        return {}

    graph = StateGraph(State)
    for name, node in [("collect", collect), ("summarize", summarize), ("write_file", write_file), ("announce", announce)]:
        graph.add_node(name, node)
    graph.add_edge(START, "collect")
    graph.add_edge("collect", "summarize")
    graph.add_edge("summarize", "write_file")
    graph.add_edge("write_file", "announce")
    graph.add_edge("announce", END)
    return graph.compile(checkpointer=checkpointer)


def run(graph, thread_id: str, version: str, durability: str = "sync") -> None:
    config = {"configurable": {"thread_id": thread_id}}
    saved = graph.get_state(config)
    if saved.next:  # an unfinished run on this thread: resume it from its last checkpoint
        print(f"resuming {thread_id} at {saved.next[0]}")
        stream = graph.stream(None, config, stream_mode="updates", durability=durability)
    else:
        stream = graph.stream({"version": version}, config, stream_mode="updates", durability=durability)
    for update in stream:
        print("finished", *update)
        crash_point(f"after {next(iter(update))}")


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("--thread", required=True)
    args.add_argument("--version", default="2.5.0")
    args.add_argument("--durability", default="sync", choices=["sync", "async", "exit"])
    args.add_argument("--work-dir", type=Path, default=HERE,
                      help="Directory for checkpoints.db and out/; reuse it when resuming the same thread.")
    a = args.parse_args()
    a.work_dir.mkdir(parents=True, exist_ok=True)
    OUT = a.work_dir / "out"
    with SqliteSaver.from_conn_string(str(a.work_dir / "checkpoints.db")) as saver:
        run(build_graph(saver), a.thread, a.version, a.durability)
