"""Run the docs assistant as an A2A server and the release coordinator as its client, on Gemini.

Run from this folder with GOOGLE_API_KEY set: python record.py
Both sides run in this process (the server in a uvicorn thread), so both sides' model turns
and the JSON-RPC exchange between them are recorded. Writes recorded-runs.json and run-output.txt.
"""
import asyncio
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import httpx  # noqa: E402

import client  # noqa: E402
import server  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTIONS = {"rollback": "How do I roll back production to r41?"}


def recorder(turns: list):
    def keep_turn(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)
    return keep_turn


def sse(text: str) -> list:
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]


def wire(timeout: float = 60) -> tuple[httpx.AsyncClient, list]:
    """An httpx client that keeps every request and response body the A2A client sends and receives."""
    exchange = []

    async def on_response(response):
        await response.aread()
        body = response.request.content.decode() or None
        exchange.append({"method": response.request.method, "path": response.request.url.path,
                         "request": json.loads(body) if body else None, "status": response.status_code,
                         "response": response.json() if "json" in response.headers.get("content-type", "")
                         else sse(response.text)})
    return httpx.AsyncClient(timeout=timeout, event_hooks={"response": [on_response]}), exchange


async def run(question: str, url: str, remote_turns: list, http_timeout: float = 60, **remote) -> dict:
    turns = []
    http, exchange = wire(http_timeout)
    coordinator = client.build_agent(remote=client.remote_docs(url, httpx_client=http, **remote)).clone(
        update={"after_model_callback": recorder(turns)})
    del remote_turns[:]
    try:
        events = await client.ask(question, coordinator)
        transcript = client.show(events)
    except Exception as error:  # noqa: BLE001 - a failure run records what the client raised
        transcript = f"raised {type(error).__name__}: {error}"
    await http.aclose()
    return {"question": question, "transcript": transcript, "model_turns": turns,
            "remote_model_turns": list(remote_turns), "exchange": exchange}


async def main() -> None:
    remote_turns = []
    docs = server.build_agent().clone(update={"after_model_callback": recorder(remote_turns)})
    port = server.free_port()
    record = {"model": server.MODEL, "runs": {}, "failures": {}}
    with server.running(server.build_app(docs, port), port) as url:
        async with httpx.AsyncClient() as http:
            record["agent_card"] = (await http.get(f"{url}/.well-known/agent-card.json")).json()
        for key, question in QUESTIONS.items():
            record["runs"][key] = await run(question, url, remote_turns)
        # timeout= applies only to an httpx client ADK creates; ours keeps its own 60 s timeout.
        record["failures"]["timeout_ignored"] = await run(QUESTIONS["rollback"], url, remote_turns, timeout=0.5)
        record["failures"]["timeout"] = await run(QUESTIONS["rollback"], url, remote_turns, http_timeout=0.5)
    wrong = server.free_port()
    with server.running(server.build_app(docs, wrong, card_port=server.free_port()), wrong) as url:
        record["failures"]["card_url"] = await run(QUESTIONS["rollback"], url, remote_turns)
    record["failures"]["server_down"] = await run(QUESTIONS["rollback"], f"http://localhost:{server.free_port()}", remote_turns)
    text = json.dumps(record, indent=1, ensure_ascii=False) + "\n"
    (HERE / "recorded-runs.json").write_text(text, encoding="utf-8")
    out = []
    for key, r in [*record["runs"].items(), *record["failures"].items()]:
        out.append(f'$ python client.py "{r["question"]}"   # run: {key}\n{r["transcript"]}\n')
    (HERE / "run-output.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(json.dumps(record["runs"]["rollback"]["exchange"][1]["response"], indent=1)[:5000])


if __name__ == "__main__":
    asyncio.run(main())
