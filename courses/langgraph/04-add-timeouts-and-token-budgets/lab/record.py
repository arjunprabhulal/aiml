"""Run the CI triage agent on Gemini under each limit and save what happened."""
import asyncio
import json
import time

from langchain_core.messages import HumanMessage, ToolMessage

from graph import MODEL, build_graph, chat_model

SCENARIOS = [
    # name, question, graph limits
    ("answered", "Why is CI failing on pull request 415?", {}),
    ("slow-tool", "Why is CI failing on pull request 421?", {}),
    ("budget-stopped", "Why is CI failing on pull request 415?", {"token_budget": 500}),
    ("budget-overshoot", "Why is CI failing on pull request 415?", {"token_budget": 1000}),
    ("slow-model", "Why is CI failing on pull request 415?", {"model_timeout": 0.5}),
]


async def run(name, question, limits) -> dict:
    graph = build_graph(chat_model(), **limits)
    state = {"messages": [HumanMessage(question)], "tokens": 0}
    steps, outcome, mark = [], "answered", time.perf_counter()
    async for kind, data in graph.astream(state, {"recursion_limit": 12}, stream_mode=["updates", "values"]):
        if kind == "values":
            state = data
            continue
        node, delta = next(iter(data.items()))
        now = time.perf_counter()
        step = {"node": node, "seconds": round(now - mark, 1)}
        mark = now
        if node == "tools":
            step["results"] = [m.content for m in delta["messages"] if isinstance(m, ToolMessage)]
        if node == "agent":
            usage = delta["messages"][-1].usage_metadata or {}
            step["usage_known"] = delta["usage_known"]
            if delta["usage_known"]:
                step["tokens"] = delta["tokens"]
            details = usage.get("output_token_details") if isinstance(usage, dict) else None
            step["reasoning"] = details.get("reasoning") if isinstance(details, dict) else None
        steps.append(step)
        outcome = delta.get("stop_reason", outcome)
    last = state["messages"][-1]
    return {"scenario": name, "question": question, "limits": limits,
            "outcome": outcome, "tokens": state["tokens"], "usage_known": state.get("usage_known", False), "steps": steps,
            "final": getattr(last, "text", last)}


async def main() -> None:
    runs = [await run(*s) for s in SCENARIOS]
    with open("runs.json", "w") as f:
        json.dump({"model": MODEL, "runs": runs}, f, indent=1)
    for r in runs:
        print(f"== {r['scenario']}: {r['question']} limits={r['limits']}")
        for step in r["steps"]:
            detail = (f"{step['tokens']} tokens ({step['reasoning']} reasoning)" if "tokens" in step else
                      "model usage unavailable" if step.get("usage_known") is False else
                      " | ".join(x[:70] for x in step.get("results", [])))
            print(f"  {step['node']:<6} {step['seconds']:>5}s  {detail}")
        label = "tokens" if r["usage_known"] else "known subtotal; run total unknown"
        print(f"  outcome: {r['outcome']}  {label}: {r['tokens']}")
        print(f"  final:   {r['final'][:200]}")


if __name__ == "__main__":
    asyncio.run(main())
