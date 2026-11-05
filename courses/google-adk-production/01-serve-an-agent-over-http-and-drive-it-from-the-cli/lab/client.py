"""Drive the docs assistant through the ADK API server over HTTP.

Start the server from this folder first:
    adk api_server --port 8765 --session_service_uri sqlite:///sessions.db .
Then: python client.py "How do I undo the last production deploy?"
"""
import argparse
import json
import os
import uuid

import httpx

BASE_URL = os.environ.get("ADK_URL", "http://127.0.0.1:8765")
APP, USER = "docs_assistant", "dev-1"


def create_session(client: httpx.Client, session_id: str, state: dict | None = None) -> dict:
    """POST /apps/{app}/users/{user}/sessions with the session ID in the body."""
    r = client.post(f"/apps/{APP}/users/{USER}/sessions", json={"session_id": session_id, "state": state or {}})
    r.raise_for_status()
    return r.json()


def message(text: str) -> dict:
    return {"role": "user", "parts": [{"text": text}]}


def run(client: httpx.Client, session_id: str, text: str) -> list[dict]:
    """POST /run: the server runs the whole turn and returns every event at once."""
    body = {"app_name": APP, "user_id": USER, "session_id": session_id, "new_message": message(text)}
    r = client.post("/run", json=body)
    r.raise_for_status()
    return r.json()


def run_sse(client: httpx.Client, session_id: str, text: str, streaming: bool = True):
    """POST /run_sse: one server-sent event per ADK event, as the runner yields it."""
    body = {"app_name": APP, "user_id": USER, "session_id": session_id,
            "new_message": message(text), "streaming": streaming}
    with client.stream("POST", "/run_sse", json=body) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("data: "):
                yield json.loads(line[len("data: "):])


def describe(event: dict) -> str:
    """One line per event: author, partial or final, and what the parts carry."""
    parts = (event.get("content") or {}).get("parts") or []
    what = []
    for p in parts:
        if "functionCall" in p:
            what.append(f"call {p['functionCall']['name']}({json.dumps(p['functionCall']['args'])})")
        elif "functionResponse" in p:
            what.append(f"result {p['functionResponse']['name']}")
        elif p.get("text") and not p.get("thought"):
            what.append(repr(p["text"][:40]))
    if not what:
        what.append("(no text)")
    kind = "partial" if event.get("partial") else "final"
    return f"{event['author']:<15} {kind:<8} {' + '.join(what)}"


def answer(events: list[dict]) -> str:
    """The text of the agent's last complete event."""
    for event in reversed(events):
        if event["author"] != "user" and not event.get("partial"):
            texts = [p["text"] for p in (event.get("content") or {}).get("parts", []) if p.get("text") and not p.get("thought")]
            if texts:
                return "".join(texts)
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--stream", action="store_true", help="use /run_sse with streaming")
    args = parser.parse_args()
    with httpx.Client(base_url=BASE_URL, timeout=120) as client:
        print("apps:", client.get("/list-apps").json())
        sid = f"s-{uuid.uuid4().hex[:8]}"
        create_session(client, sid, {"team": "payments"})
        events = list(run_sse(client, sid, args.question)) if args.stream else run(client, sid, args.question)
        for event in events:
            print(describe(event))
        print("answer:", answer(events))


if __name__ == "__main__":
    main()
