"""Record the docs assistant calling the local release API through OpenAPIToolset, on Gemini.

Run from this folder with GOOGLE_API_KEY set: python record.py --record
Starts ship_api on 127.0.0.1:8766 with a random API key, which is never written to disk.
Writes recorded-runs.json and run-output.txt. The tests replay the model turns offline.
"""
import asyncio
import json
import os
import secrets
import threading
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["SHIP_API_KEY"] = secrets.token_urlsafe(24)

import uvicorn  # noqa: E402
from google.adk import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402

import assistant  # noqa: E402
import ship_api  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTIONS = [
    "Which staging releases failed, and why?",
    "What is live in production right now?",
    "Roll production back to r39.",
]


def serve() -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(ship_api.app, host="127.0.0.1", port=8766, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


def recording(agent, turns: list, declarations: list):
    def before(callback_context, llm_request):
        if not declarations:
            declarations.extend(f.model_dump(mode="json", exclude_none=True)
                                for t in llm_request.config.tools for f in t.function_declarations)

    def after(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)
    return agent.clone(update={"before_model_callback": before, "after_model_callback": after})


async def conversation(tools, questions: list) -> dict:
    turns, declarations = [], []
    runner = Runner(app_name="docs", agent=recording(assistant.make_agent(tools), turns, declarations),
                    session_service=InMemorySessionService(), auto_create_session=True)
    steps = []
    for question in questions:
        start_turns, start_requests = len(turns), len(ship_api.REQUESTS)
        error = None
        try:
            events = await assistant.ask(runner, "s1", question)
        except Exception as exc:  # recorded as a failure, not hidden
            events, error = [], f"{type(exc).__name__}: {exc}"
        answer = next(("".join(p.text or "" for p in e.content.parts if not p.thought).strip()
                       for e in reversed(events) if e.is_final_response() and e.content), "")
        steps.append({
            "question": question,
            "calls": [{"name": c.name, "args": c.args} for e in events for c in e.get_function_calls()],
            "results": [r.response for e in events for r in e.get_function_responses()],
            "http": ship_api.REQUESTS[start_requests:], "model_turns": turns[start_turns:],
            "answer": answer, "error": error,
        })
    await runner.close()
    return {"tools": [t.name for t in await tools.get_tools()], "declarations": declarations, "steps": steps}


async def main() -> None:
    server = serve()
    spec = assistant.load_spec()
    key = os.environ["SHIP_API_KEY"]
    main_run = await conversation(assistant.release_tools(spec, key), QUESTIONS)
    wrong_key = await conversation(assistant.release_tools(spec, "not-the-key"), QUESTIONS[:1])
    camel = assistant.release_tools(spec, key, tool_filter=["listReleases", "getRelease"])
    no_servers = await conversation(assistant.release_tools({k: v for k, v in spec.items() if k != "servers"}, key),
                                    QUESTIONS[:1])
    server.should_exit = True
    record = {
        "model": assistant.MODEL,
        "operations": {path: {m: op["operationId"] for m, op in ops.items()} for path, ops in spec["paths"].items()},
        "security_schemes": spec["components"]["securitySchemes"],
        "run": main_run,
        "failures": {"wrong_key": wrong_key, "camel_case_filter": [t.name for t in await camel.get_tools()],
                     "no_servers": no_servers},
    }
    text = json.dumps(record, indent=2)
    assert key not in text, "the API key must never be recorded"
    (HERE / "recorded-runs.json").write_text(text + "\n", encoding="utf-8")
    lines = [f"tools: {main_run['tools']}", ""]
    for label, run in [("main", main_run), ("wrong key", wrong_key), ("spec without servers", no_servers)]:
        for s in run["steps"]:
            lines.append(f"# {label}\n> {s['question']}")
            lines += [f"call   {c['name']} {json.dumps(c['args'])}" for c in s["calls"]]
            lines += [f"http   {h['method']} {h['path']} key_sent={h['key_sent']} request_id={h['request_id'][:10]}..."
                      for h in s["http"]]
            lines += [f"result {json.dumps(r)[:160]}" for r in s["results"]]
            lines.append(f"error  {s['error']}" if s["error"] else "answer " + s["answer"].replace("\n", " ")[:220])
            lines.append("")
    lines.append(f"# tool_filter with operationIds: {record['failures']['camel_case_filter']}")
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
