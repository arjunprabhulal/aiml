"""Record the docs assistant served by `adk api_server`, driven over HTTP and from `adk run`.

Run from this folder with GOOGLE_API_KEY set: python record.py --record
Starts the server on port 8765, writes run-output.txt and recorded-runs.json, then stops it.
"""
import json
import os
import subprocess
import socket
import sys
import time
from pathlib import Path

import httpx

import client as c

HERE = Path(__file__).resolve().parent
ADK = str(Path(sys.executable).with_name("adk"))
QUESTION = "How do I undo the last production deploy?"
ENV = {**os.environ, "GOOGLE_GENAI_USE_ENTERPRISE": "0", "GOOGLE_GENAI_USE_VERTEXAI": "0", "PYTHONWARNINGS": "ignore"}
SERVER = [ADK, "api_server", "--port", "8765", "--session_service_uri", "sqlite:///sessions.db",
          "--allow_origins", "http://localhost:3000", "."]


def model_turns(events):
    """The model's own responses, which the offline tests replay; thought signatures dropped."""
    turns = []
    for e in events:
        content = e.get("content") or {}
        if content.get("role") == "model":
            parts = [{k: v for k, v in p.items() if k != "thoughtSignature"} for p in content["parts"]]
            turns.append({"content": {"role": "model", "parts": parts}, "partial": bool(e.get("partial"))})
    return turns


def public_projection(value):
    """Omit opaque provider signatures without changing text, tool or usage fields."""
    opaque = {"thoughtSignature", "thought_signature", "functionCallSignature", "function_call_signature"}
    if isinstance(value, dict):
        return {key: public_projection(child) for key, child in value.items() if key not in opaque}
    if isinstance(value, list):
        return [public_projection(child) for child in value]
    return value


def short(event):
    keep = {k: event[k] for k in ("author", "invocationId", "partial", "content", "finishReason", "usageMetadata") if k in event}
    return public_projection(keep)


def main() -> None:
    # Select a free loopback port; never attach to another operator's server.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server_command = list(SERVER)
    server_command[server_command.index("--port") + 1] = str(port)
    server_command += ["--host", "127.0.0.1"]
    (HERE / "sessions.db").unlink(missing_ok=True)
    out, rec = [], {"model": "gemini-3.8-flash", "question": QUESTION, "server": " ".join(["adk", *server_command[1:]])}
    log_path = HERE / "server-recording.log"
    server_log = log_path.open("w")
    server = subprocess.Popen(server_command, cwd=HERE, env=ENV, stdout=server_log, stderr=subprocess.STDOUT)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120) as http:
            for _ in range(60):
                try:
                    if server.poll() is not None:
                        raise RuntimeError("Recording server stopped during startup")
                    response = http.get("/list-apps")
                    response.raise_for_status()
                    rec["apps"] = response.json()
                    break
                except httpx.ConnectError:
                    time.sleep(0.5)
            session = c.create_session(http, "s-run", {"team": "payments"})
            rec["created"] = {k: session[k] for k in ("id", "appName", "userId", "state", "events")}
            out += [f"$ {rec['server']}", f"$ python client.py {QUESTION!r}", f"apps: {rec['apps']}"]
            events = c.run(http, "s-run", QUESTION)
            rec["run"] = {"lines": [c.describe(e) for e in events], "answer": c.answer(events),
                          "events": [short(e) for e in events], "model_turns": model_turns(events)}
            out += rec["run"]["lines"] + [f"answer: {rec['run']['answer']}", ""]

            c.create_session(http, "s-sse")
            t0, seconds, streamed = time.perf_counter(), [], []
            for e in c.run_sse(http, "s-sse", QUESTION):
                streamed.append(e)
                seconds.append(round(time.perf_counter() - t0, 2))
            stored = http.get(f"/apps/{c.APP}/users/{c.USER}/sessions/s-sse").json()
            rec["sse"] = {"lines": [c.describe(e) for e in streamed], "seconds": seconds, "answer": c.answer(streamed),
                          "stored": len(stored["events"]), "model_turns": model_turns(streamed)}
            out += [f"$ python client.py --stream {QUESTION!r}"] + rec["sse"]["lines"]
            out += [f"yielded {len(streamed)} events; the session stored {rec['sse']['stored']}", ""]

            fail = {}
            body = {"app_name": c.APP, "user_id": c.USER, "session_id": "no-such-session", "new_message": c.message("hi")}
            r = http.post("/run", json=body)
            fail["unknown_session"] = {"status": r.status_code, "body": r.json()}
            body["session_id"] = "s-run"
            r = http.post("/run", json=body, headers={"Origin": "https://docs-portal.example"})
            fail["origin"] = {"status": r.status_code, "body": r.text}
            r = http.options("/run", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
            fail["allowed_origin"] = {"status": r.status_code, "allow_origin": r.headers.get("access-control-allow-origin")}
            r = http.post(f"/apps/{c.APP}/users/{c.USER}/sessions/s-old", json={"state": {"team": "payments"}})
            fail["deprecated_path"] = {"status": r.status_code, "state": r.json()["state"]}
            rec["failures"] = fail
            out += ["$ curl -X POST /run with session_id no-such-session", f"HTTP {fail['unknown_session']['status']} {json.dumps(fail['unknown_session']['body'])}",
                    "$ curl -X POST /run -H 'Origin: https://docs-portal.example'", f"HTTP {fail['origin']['status']} {fail['origin']['body']}",
                    "$ curl -X POST /apps/docs_assistant/users/dev-1/sessions/s-old -d '{\"state\": {\"team\": \"payments\"}}'",
                    f"HTTP {fail['deprecated_path']['status']} state: {json.dumps(fail['deprecated_path']['state'])}", ""]
    finally:
        server.terminate()
        server.wait(timeout=20)

    cli = [ADK, "run", "--in_memory", "--replay", "replay.json", "docs_assistant"]
    proc = subprocess.run(cli, cwd=HERE, env=ENV, capture_output=True, text=True, timeout=300)
    lines = [l for l in proc.stdout.splitlines() if l.strip() and not l.startswith(("Log setup", "To access latest log"))]
    rec["cli_replay"] = {"command": "adk run --in_memory --replay replay.json docs_assistant", "stdout": lines, "exit": proc.returncode}
    out += [f"$ {rec['cli_replay']['command']}"] + lines + [""]
    cli = [ADK, "run", "--in_memory", "--jsonl", "docs_assistant", "Which page explains tokens?"]
    proc = subprocess.run(cli, cwd=HERE, env=ENV, capture_output=True, text=True, timeout=300)
    jsonl = [json.loads(l) for l in proc.stdout.splitlines() if l.startswith("{")]
    rec["cli_jsonl"] = {"command": "adk run --in_memory --jsonl docs_assistant 'Which page explains tokens?'", "records": public_projection(jsonl)}
    out += [f"$ {rec['cli_jsonl']['command']}"] + [json.dumps(j)[:150] + " …" for j in jsonl]
    (HERE / "sessions.db").unlink(missing_ok=True)
    (HERE / "run-output.txt").write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    (HERE / "recorded-runs.json").write_text(json.dumps(public_projection(rec), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Optional live-model recording; overwrites saved run files.")
    parser.add_argument("--record", action="store_true", help="explicitly allow live model calls and record replacement")
    args = parser.parse_args()
    if not args.record:
        parser.error("recording is opt-in: use --record; normal lesson commands do not need this script")
    main()
