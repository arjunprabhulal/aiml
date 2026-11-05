"""Run the review agent and save completed graph steps, proposed tool calls and answers."""
import json

from langchain_core.messages import HumanMessage

from graph import MODEL, build_graph

QUESTIONS = [
    "Which open pull request has failing CI, and why?",
    "What does pull request 418 change, and did its CI pass?",
    "Is CI green on pull request 999?",
]


def compact(m) -> str:
    """One line per message in the graph state, in the order the add_messages reducer kept them."""
    if m.type == "ai" and m.tool_calls:
        return "ai: calls " + ", ".join(c["name"] for c in m.tool_calls)
    return f"{m.type}: {m.name}" if m.type == "tool" else m.type


def run(graph, question: str, limit: int = 12) -> dict:
    steps, answer, error, state = [], None, None, []
    try:
        for kind, update in graph.stream({"messages": [HumanMessage(question)]}, {"recursion_limit": limit},
                                         stream_mode=["updates", "values"]):
            if kind == "values":
                state = [compact(m) for m in update["messages"]]
                continue
            # One update per completed node run; a failed node emits no update. Only one node runs at a time in this graph, so each update is one graph
            # step: ToolNode runs all the calls of one AIMessage in one step, however many ToolMessages it returns.
            for node, delta in update.items():
                if node == "tools":
                    steps.append({"node": node, "results": [{"tool": m.name, "status": m.status, "content": m.content}
                                                            for m in delta["messages"]]})
                    continue
                m = delta["messages"][-1]
                if m.tool_calls:
                    steps.append({"node": node, "tool_calls": [{"name": c["name"], "args": c["args"]} for c in m.tool_calls]})
                else:
                    steps.append({"node": node, "answer": m.text})
                    answer = m.text
    except Exception as e:  # recorded, not hidden: the run stops with this exception
        error = f"{type(e).__name__}: {e}"
    return {"question": question, "recursion_limit": limit, "state": state, "path": [s["node"] for s in steps],
            "graph_steps": len(steps), "model_calls": sum(s["node"] == "agent" for s in steps),
            "tool_calls": sum(len(s.get("tool_calls", [])) for s in steps), "messages": len(state),
            "steps": steps, "answer": answer, "error": error}


def main() -> None:
    runs = [run(build_graph(), q) for q in QUESTIONS]
    # The unknown pull request again, with ToolNode's default error handling.
    runs.append({**run(build_graph(catch_unknown_pr=False), QUESTIONS[2]), "catch_unknown_pr": False})
    # The first question again with too few steps for the tool calls it makes.
    runs.append(run(build_graph(), QUESTIONS[0], limit=4))
    with open("runs.json", "w") as f:
        json.dump({"model": MODEL, "runs": runs}, f, indent=1)
    for r in runs:
        note = "  [default tool errors]" if r.get("catch_unknown_pr") is False else ""
        print(f"== {r['question']}{note}  (recursion_limit={r['recursion_limit']})")
        for s in r["steps"]:
            if "tool_calls" in s:
                print("  agent  ->", ", ".join(f"{c['name']}({json.dumps(c['args'])})" for c in s["tool_calls"]))
            elif "results" in s:
                for i, t in enumerate(s["results"]):
                    print("  tools  ->" if i == 0 else "           ", f"{t['tool']} [{t['status']}]: {t['content']}")
        print("  answer:", r["answer"]) if r["answer"] else print("  error: ", r["error"].splitlines()[0])
        print("  state: ", " | ".join(r["state"]))
        print(f"  completed graph steps: {r['graph_steps']} ({' → '.join(r['path'])}), model calls: {r['model_calls']},"
              f" tool calls: {r['tool_calls']}, messages in state: {r['messages']}")


if __name__ == "__main__":
    main()
