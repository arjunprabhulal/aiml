"""Record two runs of the docs assistant against one artifact store on disk, on Gemini.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes recorded-runs.json and run-output.txt. The tests replay the model turns offline.
"""
import asyncio
import json
import shutil
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from google.adk import Runner  # noqa: E402
from google.adk.artifacts import FileArtifactService  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

import assistant  # noqa: E402

HERE = Path(__file__).resolve().parent
STORE = HERE / "artifact-store"
STEPS = [  # (run, message): run 2 uses a new Runner and session on the same store in this process
    (1, "upload", "Review this ship.toml before I deploy it to production."),
    (1, "text", "Save that review as review.md."),
    (1, "text", "We will fix all three problems before the deploy. Add that decision to the review and save it again."),
    (1, "text", "Save a five-item production deploy checklist for me as user:checklist.md, so I have it next time."),
    (2, "text", "Which files do you have for me? Show me my checklist."),
]


def recording_agent(turns: list, requests: list):
    def before(callback_context, llm_request):
        requests.append(json.dumps([c.model_dump(mode="json", exclude_none=True) for c in llm_request.contents]))

    def after(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)
    return assistant.root_agent.clone(update={"before_model_callback": before, "after_model_callback": after})


def tree(store: Path) -> list[str]:
    return [str(p.relative_to(store)) for p in sorted(store.rglob("*")) if p.is_file()]


async def failures() -> dict:
    out = {}
    service = FileArtifactService(root_dir=STORE)
    # 1. A filename the model chose that walks out of the store is refused.
    for bad in ["../../ship.toml", "/etc/hosts"]:
        try:
            await service.save_artifact(app_name="docs", user_id="dana", session_id="x", filename=bad,
                                        artifact=types.Part(text="x"))
        except Exception as error:  # InputValidationError
            out.setdefault("traversal", []).append(f"{type(error).__name__}: {error}")
    # 2. Loading a file that does not exist returns None, not an error.
    out["missing"] = repr(await service.load_artifact(app_name="docs", user_id="dana", session_id="x",
                                                      filename="review.md"))
    # 3. No artifact service on the Runner: the tool's save_artifact call raises.
    runner = Runner(app_name="docs", agent=assistant.root_agent, session_service=InMemorySessionService(),
                    auto_create_session=True)
    try:
        await assistant.ask(runner, "dana", "no-store", "Save the text 'hello' as note.md.")
    except ValueError as error:
        out["no_service"] = f"{type(error).__name__}: {error}"
    await runner.close()
    return out


async def main() -> None:
    shutil.rmtree(STORE, ignore_errors=True)
    steps, runner, run = [], None, None
    for n, (run_no, kind, text) in enumerate(STEPS, 1):
        if run_no != run:
            if runner:
                await runner.close()
            turns, requests = [], []
            runner, run = assistant.make_runner(recording_agent(turns, requests)), run_no
            session = await runner.session_service.create_session(app_name="docs", user_id="dana")
        start_turns, start_requests = len(turns), len(requests)
        message = assistant.upload(HERE / "ship.toml", text) if kind == "upload" else text
        events = await assistant.ask(runner, "dana", session.id, message)
        answer = next(("".join(p.text or "" for p in e.content.parts if not p.thought).strip()
                       for e in reversed(events) if e.is_final_response() and e.content), "")
        steps.append({
            "step": n, "run": run_no, "kind": kind, "message": text,
            "calls": [{"name": c.name, "args": c.args} for e in events for c in e.get_function_calls()],
            "artifact_delta": {k: v for e in events for k, v in e.actions.artifact_delta.items()},
            "requests_with_file": sum("SEARCH_INDEX_URL" in r for r in requests[start_requests:]),
            "requests": len(requests) - start_requests,
            "model_turns": turns[start_turns:], "answer": answer,
            "listed": await runner.artifact_service.list_artifact_keys(
                app_name="docs", user_id="dana", session_id=session.id),
        })
    await runner.close()
    record = {"model": assistant.MODEL, "steps": steps, "store": tree(STORE),
              "failures": await failures()}
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    lines = []
    for s in steps:
        lines.append(f"# run {s['run']}, step {s['step']}" + (" (ship.toml attached)" if s["kind"] == "upload" else ""))
        lines.append(f"> {s['message']}")
        lines += [f"call   {c['name']} {json.dumps(c['args'])[:110]}" for c in s["calls"]]
        if s["artifact_delta"]:
            lines.append(f"saved  {s['artifact_delta']}")
        lines.append(f"listed {s['listed']}")
        lines.append("answer " + s["answer"].replace("\n", " ")[:300])
        lines.append("")
    lines.append("# artifact store on disk")
    lines += record["store"]
    (HERE / "run-output.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(json.dumps(record["failures"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
