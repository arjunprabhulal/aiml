"""Stream each conversation's answer through the guardrails proxy and compare it with a per-chunk filter.

    python3 run_guard.py record   # needs Ollama with the pinned gemma4:e2b; writes recorded/streams.json
    python3 run_guard.py          # offline: replays the streams through the proxy, writes results.json
    python3 run_guard.py --check  # offline: compares a fresh replay with results.json

Every replay goes over real HTTP on 127.0.0.1: the client posts to the proxy and
reads its newline-delimited JSON, as an application would. Nothing is timed;
delay is reported in characters held back and in upstream chunks.
"""
import argparse
import json
import sys
import threading
from pathlib import Path
from urllib import request as urlrequest

import guard
import proxy

HERE = Path(__file__).resolve().parent
CONVERSATIONS = json.loads((HERE / "conversations.json").read_text(encoding="utf-8"))


def request_for(message):
    return {"model": proxy.MODEL["ollama_tag"], "stream": True, "think": proxy.MODEL["think"],
            "messages": [{"role": "system", "content": CONVERSATIONS["system"]}, {"role": "user", "content": message}],
            "options": {**proxy.MODEL["options"], "seed": proxy.MODEL["seed"]}}


def through_proxy(upstream, action, payload):
    """POST to a running proxy and read its stream like a client. Return the events."""
    server = proxy.serve(upstream, action)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urlrequest.Request(f"http://127.0.0.1:{server.server_address[1]}/api/chat",
                                 data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urlrequest.urlopen(req, timeout=30) as response:
            return [json.loads(line) for line in response if line.strip()]
    finally:
        server.shutdown()
        server.server_close()


def released(events):
    return "".join(e["message"]["content"] for e in events if not e.get("done"))


def run_one(convo, recording):
    payload = request_for(convo["message"])
    chunks = recording.streams[proxy.request_sha256(payload)]["chunks"]
    text = "".join(chunks)
    row = {"id": convo["id"], "chunks": len(chunks), "answer": text,
           "per_chunk_filter": guard.per_chunk_filter(chunks)}
    for action in ("redact", "block"):
        upstream = proxy.ReplayUpstream()
        events = through_proxy(upstream, action, payload)
        row[action] = {"client_text": released(events), "client_lines": len(events),
                       "final": events[-1], "upstream_chunks_read": len(upstream.read)}
    # The guard's output must not depend on how the model happened to split its answer.
    reference = "".join(guard.guarded([text])[0])
    row["same_output_for_any_chunking"] = all(
        "".join(guard.guarded([text[i:i + n] for i in range(0, len(text), n)])[0]) == reference for n in (1, 2, 3, 5, 8, 13))
    return row


def results():
    recording = proxy.ReplayUpstream()
    return {"model": proxy.MODEL["ollama_tag"], "conversations": [run_one(c, recording) for c in CONVERSATIONS["conversations"]]}


def record(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", choices=["record"])
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args(argv)
    if options.command == "record":
        upstream = proxy.OllamaUpstream()
        for convo in CONVERSATIONS["conversations"]:
            for _ in upstream.stream(request_for(convo["message"])):
                pass
        proxy.RECORDING.write_text(json.dumps({"model": proxy.MODEL, "streams": dict(sorted(upstream.recorded.items()))},
                                              indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"recorded {len(upstream.recorded)} streams")
        return
    fresh = results()
    for row in fresh["conversations"]:
        print(f"{row['id']}: {row['chunks']} chunks")
        print(f"   per-chunk filter: {row['per_chunk_filter']!r}")
        print(f"   proxy redact:     {row['redact']['client_text']!r}  {row['redact']['final']['guardrail']}")
        print(f"   proxy block:      {row['block']['client_text']!r}  read {row['block']['upstream_chunks_read']} of {row['chunks']}")
    if options.check:
        if (HERE / "results.json").read_text(encoding="utf-8") != record(fresh):
            sys.exit("results.json differs from a fresh replay")
        print("results.json matches")
        return
    (HERE / "results.json").write_text(record(fresh), encoding="utf-8")
    print("wrote results.json")


if __name__ == "__main__":
    main()
