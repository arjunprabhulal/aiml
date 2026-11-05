"""Record one parallel tool call on Gemini, then replay it against four tool variants.

Run from this folder with GOOGLE_API_KEY set: python record.py --record
Starts docs_server on 127.0.0.1:8770. Writes recorded-runs.json and run-output.txt.
"""
import asyncio
import json
import threading
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import uvicorn  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

import assistant  # noqa: E402
import docs_server  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTION = "Check that the rollback, migrations, hooks, approvals and canary pages are reachable."
VARIANTS = [  # (label, tool, run_config)
    ("async tool", assistant.fetch_page, None),
    ("sync tool", assistant.fetch_page_blocking, None),
    ("sync tool + thread pool", assistant.fetch_page_blocking, assistant.THREAD_POOL),
    ("async def that blocks + thread pool", assistant.fetch_page_async_but_blocking, assistant.THREAD_POOL),
]


class ReplayLlm(BaseLlm):
    turns: list

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def serve() -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(docs_server.app, host="127.0.0.1", port=8770, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


def overlap(served: list[dict]) -> dict:
    """How long the page fetches took end to end, and how many were in flight at once."""
    span = max(s["end"] for s in served) - min(s["start"] for s in served)
    peak = max(sum(1 for o in served if o["start"] <= s["start"] < o["end"]) for s in served)
    return {"requests": len(served), "span_seconds": round(span, 2), "max_in_flight": peak}


def renamed(turns: list, name: str) -> list:
    out = json.loads(json.dumps(turns))
    for turn in out:
        for part in turn.get("parts", []):
            if "function_call" in part:
                part["function_call"]["name"] = name
    return out


async def live() -> dict:
    turns = []

    def keep(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)
    docs_server.SERVED.clear()
    events = await assistant.ask(assistant.make_agent().clone(update={"after_model_callback": keep}), QUESTION)
    calls = [{"name": c.name, "args": c.args} for e in events for c in e.get_function_calls()]
    answer = "".join(p.text or "" for p in events[-1].content.parts if not p.thought).strip()
    return {"calls": calls, "calls_per_model_turn": [sum("function_call" in p for p in t.get("parts", [])) for t in turns],
            "results": [r.response for e in events for r in e.get_function_responses()],
            "server": overlap(docs_server.SERVED), "model_turns": turns, "answer": answer}


async def replayed(turns: list, label: str, tool, run_config) -> dict:
    docs_server.SERVED.clear()
    agent = assistant.make_agent(tool).clone(update={"model": ReplayLlm(model="replay", turns=renamed(turns, tool.__name__))})
    start = time.perf_counter()
    await assistant.ask(agent, QUESTION, run_config)
    return {"variant": label, "tool": tool.__name__, "thread_pool": run_config is not None,
            "wall_seconds": round(time.perf_counter() - start, 2), **overlap(docs_server.SERVED)}


async def main() -> None:
    server = serve()
    run = await live()
    matrix = [await replayed(run["model_turns"], *v) for v in VARIANTS]
    server.should_exit = True
    record = {"model": assistant.MODEL, "server_delay_seconds": docs_server.DELAY_SECONDS, "question": QUESTION,
              "live": run, "matrix": matrix}
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    lines = [f"> {QUESTION}", f"model turns: {run['calls_per_model_turn']} function calls per turn"]
    lines += [f"call   {c['name']} {c['args']}" for c in run["calls"]]
    lines += [f"result {json.dumps(r)}" for r in run["results"]]
    lines += [f"server {run['server']}", "answer " + run["answer"].replace("\n", " "), "",
              f"# the same model turns replayed; the docs host takes {docs_server.DELAY_SECONDS}s per page"]
    lines += [f"{m['variant']:<38} span={m['span_seconds']}s in_flight={m['max_in_flight']} wall={m['wall_seconds']}s"
              for m in matrix]
    (HERE / "run-output.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Optional live-model recording; overwrites saved run files.")
    parser.add_argument("--record", action="store_true", help="explicitly allow live model calls and record replacement")
    args = parser.parse_args()
    if not args.record:
        parser.error("recording is opt-in: use --record; normal lesson commands do not need this script")
    asyncio.run(main())
