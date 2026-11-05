"""Run the review agent on Gemini across separate threads that share one store, and save what it stored."""
import json

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from graph import MODEL, ReviewContext, build_graph, namespace

STEPS = [  # thread, repository, message
    ("t1", "acme/api", "Remember for this repository: the maximum line length is 88 characters."),
    ("t2", "acme/api", "We changed the rule. The maximum line length is now 100 characters; remember that."),
    ("t3", "acme/api", "Review pull request 501. Does it follow our line-length rule?"),
    ("t4", "acme/web", "Review pull request 502. Does it follow our line-length rule?"),
]


def snapshot(store, prefix):
    return [{"namespace": list(i.namespace), "key": i.key if len(i.key) < 20 else "<uuid4>", "value": i.value} for i in store.search(prefix, limit=50)]


def run(key_by_topic: bool) -> dict:
    store = InMemoryStore()
    graph = build_graph(store, checkpointer=InMemorySaver(), key_by_topic=key_by_topic)
    threads = []
    for thread, repo, text in STEPS:
        result = graph.invoke({"messages": [HumanMessage(text)]}, {"configurable": {"thread_id": thread}},
                              context=ReviewContext(repo=repo))
        calls = [{"name": c["name"], "args": c["args"]} for m in result["messages"] for c in getattr(m, "tool_calls", [])]
        results = [m.content for m in result["messages"] if m.type == "tool"]
        threads.append({"thread": thread, "repo": repo, "message": text, "tool_calls": calls, "tool_results": results,
                        "answer": result["messages"][-1].text, "store_after": snapshot(store, namespace(repo))})
    # Thread state is per thread: t3 starts with none of t1's or t2's messages, yet it read their rule.
    per_thread = {t: [m.type for m in graph.get_state({"configurable": {"thread_id": t}}).values["messages"]]
                  for t, _, _ in STEPS}
    return {"key_by_topic": key_by_topic, "threads": threads, "thread_messages": per_thread,
            "prefix_search": snapshot(store, ("conventions",))}


def print_store(r) -> None:
    print("  search(('conventions',)):", json.dumps(r["prefix_search"]))


def main() -> None:
    runs = [run(True), run(False)]
    with open("runs.json", "w") as f:
        json.dump({"model": MODEL, "runs": runs}, f, indent=1)
    for r in runs:
        print(f"#### keys: {'topic' if r['key_by_topic'] else 'uuid4 per memory'}")
        for t in r["threads"]:
            print(f"== {t['thread']} [{t['repo']}] {t['message']}")
            for c, out in zip(t["tool_calls"], t["tool_results"]):
                print(f"  agent -> {c['name']}({json.dumps(c['args'])})")
                print(f"  tools -> {out}")
            print(f"  answer: {t['answer']}")
            print(f"  thread {t['thread']} messages: {' | '.join(r['thread_messages'][t['thread']])}")
            print(f"  store {json.dumps(namespace(t['repo']))}: {json.dumps([(i['key'], i['value']['rule']) for i in t['store_after']])}")
        print_store(r)


if __name__ == "__main__":
    main()
