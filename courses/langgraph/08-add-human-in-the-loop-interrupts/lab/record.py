"""Run the review agent on Gemini, answer each pause as a human reviewer would, and save the runs."""
import json

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

import review_queue
from graph import MODEL, build_graph, resume

TASK = "Review pull request {n} and post your review comment."
CASES = [  # thread, pull request, the reviewer's decision
    ("review-415", 415, {"action": "approve"}),
    ("review-412", 412, {"action": "edit", "body": "Looks good. Please log each retry so we can see 503 bursts."}),
    ("review-418", 418, {"action": "reject", "reason": "the export owner already approved this deletion"}),
]


def pending(result: dict) -> list:
    return [i.value for i in result.get("__interrupt__", [])]


def checkpoint(graph, config) -> dict:
    """What the checkpointer saved for a paused thread."""
    snap = graph.get_state(config)
    return {"next": list(snap.next), "step": snap.metadata["step"], "source": snap.metadata["source"],
            "messages": [m.type + (": calls " + ", ".join(c["name"] for c in m.tool_calls) if getattr(m, "tool_calls", None) else "")
                         for m in snap.values["messages"]],
            "pending_task": snap.tasks[0].name, "interrupt_value": snap.tasks[0].interrupts[0].value,
            "checkpoints_in_history": len(list(graph.get_state_history(config)))}


def public(posted: list) -> list:
    return [{"number": p["number"], "body": p["body"]} for p in posted]


def main() -> None:
    review_queue.clear()  # the code host's SQLite file outlives each run; start from no comments
    graph = build_graph(checkpointer=InMemorySaver())
    runs = []
    for thread, n, decision in CASES:
        config = {"configurable": {"thread_id": thread}}
        first = graph.invoke({"messages": [HumanMessage(TASK.format(n=n))]}, config)
        paused = pending(first)
        waiting_at = list(graph.get_state(config).next)
        saved = checkpoint(graph, config)
        posted_while_paused = len(review_queue.posted())
        final = resume(graph, config, decision)
        runs.append({"thread": thread, "pull_request": n, "paused_with": paused, "waiting_at": waiting_at, "checkpoint_while_paused": saved,
                     "posted_while_paused": posted_while_paused, "decision": decision,
                     "paused_again": pending(final), "answer": final["messages"][-1].text,
                     "posted": public(review_queue.posted()),
                     "checkpoints_after_resume": len(list(graph.get_state_history(config)))})
        if thread == "review-415":  # a second click on Approve, after the first resume finished
            try:
                resume(graph, config, decision)
            except LookupError as e:
                runs[-1]["second_resume"] = {"error": f"LookupError: {e}", "posted": len(review_queue.posted())}
        review_queue.clear()

    failures = {}
    # The rejection again, but the model writes the reply after reading the "Not run" tool message,
    # on Gemini and on the local alternative.
    local = ChatOllama(model="gemma4:e2b", temperature=0, reasoning=False)
    for key, model in [("model_replies_to_rejection", None), ("model_replies_to_rejection_gemma4_e2b", local)]:
        config = {"configurable": {"thread_id": f"review-418-{key}"}}
        replying = build_graph(model, checkpointer=InMemorySaver(), model_replies_to_rejection=True)
        replying.invoke({"messages": [HumanMessage(TASK.format(n=418))]}, config)
        final = resume(replying, config, CASES[2][2])
        failures[key] = {"answer": final["messages"][-1].text, "posted": len(review_queue.posted())}
    config = {"configurable": {"thread_id": "review-typo"}}
    graph.invoke({"messages": [HumanMessage(TASK.format(n=415))]}, config)
    try:
        resume(graph, config, {"action": "approved"})
    except ValidationError as e:
        failures["misspelled_decision"] = {"error": f"ValidationError: {e.errors()[0]['msg']}",
                                           "still_waiting_at": list(graph.get_state(config).next),
                                           "posted": len(review_queue.posted())}
    try:
        resume(graph, {"configurable": {"thread_id": "review-4l5"}}, {"action": "approve"})
    except LookupError as e:
        failures["wrong_thread_id"] = {"error": f"LookupError: {e}"}
    # The same resume sent straight to invoke, without the guard: LangGraph starts a new run on the empty thread.
    stray_config = {"configurable": {"thread_id": "review-4l5"}}
    try:
        graph.invoke(Command(resume={"action": "approve"}), stray_config)
        error = None
    except Exception as e:  # recorded: what an unguarded resume on the wrong thread does
        error = f"{type(e).__name__}: {e}"
    state = graph.get_state(stray_config).values.get("messages", [])
    failures["unguarded_wrong_thread_id"] = {
        "messages_in_state": [m.type for m in state],
        "model_calls": [{"name": c["name"], "args": c["args"]} for m in state for c in getattr(m, "tool_calls", [])],
        "error": error, "posted": len(review_queue.posted())}
    review_queue.clear()
    no_saver = build_graph()
    paused = no_saver.invoke({"messages": [HumanMessage(TASK.format(n=415))]})
    try:
        no_saver.invoke(Command(resume={"action": "approve"}))
    except RuntimeError as e:
        failures["no_checkpointer"] = {"paused_with": pending(paused), "error": f"RuntimeError: {e}"}

    with open("runs.json", "w") as f:
        json.dump({"model": MODEL,
                   "runs": runs, "failures": failures}, f, indent=1)
    for r in runs:
        print(f"== {r['thread']}: {TASK.format(n=r['pull_request'])}")
        for p in r["paused_with"]:
            print(f"  paused: {p['tool']} {json.dumps(p['args'])}")
        print(f"  waiting at: {r['waiting_at']}")
        print(f"  comments posted while paused: {r['posted_while_paused']}")
        print(f"  resume: {json.dumps(r['decision'])}")
        print(f"  posted: {json.dumps(r['posted'])}")
        c = r["checkpoint_while_paused"]
        print(f"  checkpoint while paused: step {c['step']}, next {c['next']}, {len(c['messages'])} messages: {' | '.join(c['messages'])}")
        print(f"  checkpoints: {c['checkpoints_in_history']} while paused, {r['checkpoints_after_resume']} after resume")
        if "second_resume" in r:
            print(f"  second resume: {r['second_resume']['error']} (comments posted: {r['second_resume']['posted']})")
        print(f"  answer: {r['answer']}")
    for name, f in failures.items():
        print(f"== failure: {name}")
        for k, v in f.items():
            print(f"  {k}: {v if isinstance(v, str) else json.dumps(v)}")


if __name__ == "__main__":
    main()
