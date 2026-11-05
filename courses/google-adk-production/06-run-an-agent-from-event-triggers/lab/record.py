"""Record docs-changed events delivered to the local trigger endpoints of `adk api_server`.

Run from this folder with GOOGLE_API_KEY set: python record.py
Starts two servers: one with trigger endpoints on port 8767, one that also requires an OIDC token
on port 8768. No Google Cloud service is called: publish.py sends what Pub/Sub and Eventarc would.
Writes run-output.txt and recorded-runs.json; reviews.jsonl is temporary.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

import publish

HERE = Path(__file__).resolve().parent
ADK = str(Path(sys.executable).with_name("adk"))
REVIEWS = Path(tempfile.mkdtemp()) / "reviews.jsonl"
ENV = {**os.environ, "GOOGLE_GENAI_USE_ENTERPRISE": "0", "GOOGLE_GENAI_USE_VERTEXAI": "0", "PYTHONWARNINGS": "ignore",
       "DOCS_REVIEWS": str(REVIEWS), "TRIGGER_TOKEN": "local-dev-token"}
publish.TOKEN = "local-dev-token"
NO_AUTH = ["api_server", "--trigger_sources", "pubsub,eventarc", "--port", "8767", "."]
OIDC = ["api_server", "--trigger_sources", "pubsub", "--trigger_oidc_audience", "https://docs-reviewer.example",
        "--port", "8768", "--session_service_uri", "memory://", "."]


def start(args: list[str], port: int) -> subprocess.Popen:
    proc = subprocess.Popen(args, cwd=HERE, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            httpx.get(f"http://127.0.0.1:{port}/list-apps")
            return proc
        except httpx.ConnectError:
            time.sleep(0.5)
    raise RuntimeError(f"server on {port} did not start")


def reviews() -> list:
    return [json.loads(l) for l in REVIEWS.read_text().splitlines()] if REVIEWS.exists() else []


USERS = {"pubsub": "projects--docs--subscriptions--docs-changed",
         "eventarc": "pubsub.googleapis.com--projects--docs--topics--docs-changed"}


def new_session(http: httpx.Client, source: str, seen: set) -> dict | None:
    """The session the trigger endpoint created for the last delivery, with its events."""
    listed = http.get(f"/apps/docs_reviewer/users/{USERS[source]}/sessions").json()
    fresh = [s["id"] for s in listed if s["id"] not in seen]
    if not fresh:
        return None
    seen.add(fresh[0])
    return http.get(f"/apps/docs_reviewer/users/{USERS[source]}/sessions/{fresh[0]}").json()


def model_turns(session: dict | None) -> list:
    turns = []
    for e in (session or {}).get("events", []):
        content = e.get("content") or {}
        if content.get("role") == "model":
            turns.append({"content": {"role": "model", "parts": [{k: v for k, v in p.items() if k != "thoughtSignature"}
                                                                 for p in content["parts"]]}})
    return turns


def main() -> None:
    rec = {"model": "gemini-3.8-flash", "oidc_server": "adk " + " ".join(OIDC), "deliveries": []}
    proc = subprocess.run([ADK, *NO_AUTH], cwd=HERE, env=ENV, capture_output=True, text=True, timeout=60)
    rec["no_auth"] = {"command": "adk " + " ".join(NO_AUTH), "error": proc.stderr.strip().splitlines()[-1], "exit": proc.returncode}
    steps = [("pubsub", "tokens", "1001", None, None), ("pubsub", "tokens", "1001", None, None),
             ("eventarc", "rollback", "ev-77", None, None), ("pubsub", "tokens", "1002", "not base64!", None),
             ("pubsub", "tokens", "1004", None, "wrong-token")]
    server = start([sys.executable, "main.py"], 8767)
    try:
        seen: set = set()
        with httpx.Client(base_url="http://127.0.0.1:8767", timeout=180) as http:
            for source, page, event_id, raw, token in steps:
                t0 = time.perf_counter()
                r = publish.deliver(http, source, page, event_id, raw, token)
                rec["deliveries"].append({"command": (f"TRIGGER_TOKEN={token} " if token else "")
                                          + f"python publish.py {source} {page} --{'message' if source == 'pubsub' else 'event'}-id {event_id}"
                                          + (f" --raw-data {raw!r}" if raw else ""),
                                          "status": r.status_code, "body": r.json(), "seconds": round(time.perf_counter() - t0, 1),
                                          "reviews": reviews()})
                session = new_session(http, source, seen)
                rec["deliveries"][-1]["session"] = {"user_id": session["userId"], "state": session["state"],
                                                    "first_message": session["events"][0]["content"]["parts"][0]["text"],
                                                    "model_turns": model_turns(session)} if session else None
    finally:
        server.terminate()
        server.wait(timeout=20)
    server = start([ADK, *OIDC], 8768)
    try:
        event = REVIEWS.with_name("event.json")
        event.write_text(json.dumps(publish.pubsub_body("tokens", "1003")), encoding="utf-8")
        curl = subprocess.run(["curl", "-s", "-w", "\nHTTP %{http_code}", "-X", "POST", "-H", "Content-Type: application/json",
                               "-d", f"@{event}", "http://127.0.0.1:8768/apps/docs_reviewer/trigger/pubsub"],
                              capture_output=True, text=True, timeout=60)
        body, status = curl.stdout.rsplit("\nHTTP ", 1)
        rec["oidc_missing_token"] = {"status": int(status), "body": json.loads(body), "reviews": len(reviews())}
    finally:
        server.terminate()
        server.wait(timeout=20)
    out = [f"$ {rec['no_auth']['command']}", rec["no_auth"]["error"], f"exit {rec['no_auth']['exit']}", "",
           "$ TRIGGER_TOKEN=local-dev-token python main.py"]
    for d in rec["deliveries"]:
        out += [f"$ {d['command']}", f"HTTP {d['status']} {json.dumps(d['body'])}  ({d['seconds']} s)"]
    out += ["$ cat reviews.jsonl", *[json.dumps(r) for r in reviews()], "",
            f"$ {rec['oidc_server']}", "$ curl -s -X POST -H 'Content-Type: application/json' -d @event.json http://127.0.0.1:8768/apps/docs_reviewer/trigger/pubsub",
            f"HTTP {rec['oidc_missing_token']['status']} {json.dumps(rec['oidc_missing_token']['body'])}"]
    (HERE / "run-output.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    (HERE / "recorded-runs.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
