"""Run the code-review agent on Gemini and save the node path of every run."""
import json

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from graph import MODEL, RECURSION_LIMIT, build_graph

QUESTIONS = [
    "Which open pull request has failing CI, and why?",
    "What does pull request 418 change, and did its CI pass?",
    "Has CI been re-run on #415 since the last push? Check until it passes.",
]


def run(graph, question: str, limit: int) -> dict:
    path, calls, final, reason = [], [], None, "answered"
    try:
        for update in graph.stream({"messages": [HumanMessage(question)]},
                                   {"recursion_limit": limit}, stream_mode="updates"):
            for node, delta in update.items():
                path.append(node)
                message = delta["messages"][-1]
                calls += [{"name": c["name"], "args": c["args"]} for c in getattr(message, "tool_calls", [])]
                if node in ("agent", "stop") and not getattr(message, "tool_calls", None):
                    final = message.text
                reason = delta.get("stop_reason", reason)
    except GraphRecursionError as error:
        reason, final = "GraphRecursionError", str(error).splitlines()[0]
    return {"question": question, "recursion_limit": limit, "path": path, "steps": len(path),
            "tool_calls": calls, "outcome": reason, "final": final}


def main() -> None:
    graph = build_graph()
    runs = [run(graph, q, RECURSION_LIMIT) for q in QUESTIONS]
    # The first question again with a limit too small for two tool rounds: the step-limit branch.
    runs.append(run(graph, QUESTIONS[0], 5))
    with open("runs.json", "w") as f:
        json.dump({"model": MODEL, "runs": runs}, f, indent=1)
    for r in runs:
        print(f"== {r['question']} (recursion_limit={r['recursion_limit']})")
        print("  path:    ", " -> ".join(r["path"]))
        for c in r["tool_calls"]:
            print("  proposed:", c["name"], json.dumps(c["args"]))
        print("  outcome: ", r["outcome"], "after", r["steps"], "steps")
        print("  final:   ", r["final"])


if __name__ == "__main__":
    main()
