"""Run one code-review thread on Gemini twice, without and with a pinned decision, and save runs.json."""
import json

from langchain_core.messages import HumanMessage

from graph import BUDGET, MODEL, ContextTooLarge, build_graph

LOG = "\n".join(f"09:14:{s:02d} tests/test_client.py::test_retry_{s} PASSED [{7 * s:3d}%]" for s in range(15))
DECISION = "mlee reviews #412, and it must merge before the 2.5 freeze on November 14."
TURNS = [
    "For #415 we agreed to keep DEFAULT_TIMEOUT at 10s and add a per-client timeout override instead.",
    DECISION,
    f"Here is the CI log from #415. Does anything look wrong?\n{LOG}",
    "Draft a one-line review comment for #415.",
    "Who reviews #412, and when must it merge?",
]


def thread(graph, name: str, pin: bool) -> dict:
    config = {"configurable": {"thread_id": name}}
    turns = []
    for text in TURNS:
        update = {"messages": [HumanMessage(text)]}
        if pin and text == DECISION:
            update["pinned"] = [DECISION]
        state = graph.invoke(update, config)
        turns.append({"question": text.splitlines()[0], **state["view"], "reply": state["messages"][-1].text})
    return {"thread": name, "pinned": state.get("pinned", []), "stored_messages": len(state["messages"]), "turns": turns}


def main() -> None:
    graph = build_graph()
    runs = [thread(graph, "review", pin=False), thread(graph, "review-pinned", pin=True)]
    paste = "Check this log:\n" + "\n".join(f"09:15:{s:02d} tests/test_client.py::test_retry_{s} PASSED" for s in range(60))
    try:
        graph.invoke({"messages": [HumanMessage(paste)]}, {"configurable": {"thread_id": "paste"}})
        overflow = "no error"
    except ContextTooLarge as error:
        overflow = f"{type(error).__name__}: {error}"
    with open("runs.json", "w") as f:
        json.dump({"model": MODEL, "budget": BUDGET, "runs": runs, "overflow": overflow}, f, indent=1)
    for run in runs:
        print(f"== thread {run['thread']}  pinned={run['pinned']}")
        for t in run["turns"]:
            print(f"  sent {t['sent']:>2}/{t['stored'] + 1:<2} messages  estimate {t['estimated_tokens']:>3} "
                  f"(chars only {t['chars_only_estimate']:>3})  billed {t['server_tokens']:>3}  | {t['question'][:44]}")
        print("  last reply:", run["turns"][-1]["reply"])
    print("== a 60-line paste:", overflow)


if __name__ == "__main__":
    main()
