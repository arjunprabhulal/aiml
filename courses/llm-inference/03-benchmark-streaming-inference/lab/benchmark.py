"""Measure an actual SSE endpoint. A frame can contain multiple tokens: do not call frame gaps TPOT."""

import argparse
import concurrent.futures
import json
import math
import time
import urllib.error
import urllib.request


def request_one(url, prompt, limit):
    start = time.perf_counter()
    arrivals = []
    pieces = []
    saw_done = False
    req = urllib.request.Request(
        url,
        data=json.dumps({"prompt": prompt, "max_new_tokens": limit}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            data = []
            for raw in response:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("data:"):
                    data.append(line[5:].lstrip(" "))
                elif not line and data:
                    event = "\n".join(data)
                    data = []
                    if event == "[DONE]":
                        saw_done = True
                        break
                    payload = json.loads(event)
                    if not isinstance(payload,dict): raise ValueError("Expected an event object")
                    piece = payload.get("token", "")
                    if not isinstance(piece,str):raise ValueError("Expected text content")
                    if piece:
                        arrivals.append(time.perf_counter() - start)
                        pieces.append(piece)
        if not saw_done:raise ValueError("Stream ended without a completion marker")
        end = time.perf_counter()
        return {
            "status": "completed",
            "ttft_ms": round(arrivals[0] * 1000, 3) if arrivals else None,
            "event_gaps_ms": [
                round((b - a) * 1000, 3) for a, b in zip(arrivals, arrivals[1:])
            ],
            "e2e_ms": round((end - start) * 1000, 3),
            "text": "".join(pieces),
            "content_events": len(pieces),
        }
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return {
            "status": "failed",
            "error": str(e),
            "e2e_ms": round((time.perf_counter() - start) * 1000, 3),
        }


def run(url, prompts, limit=24, request_rate=1.0, max_in_flight=4, ttft_slo_ms=500):
    if not prompts or request_rate <= 0 or max_in_flight < 1:
        raise ValueError("Workload, rate and capacity must be positive")
    started = time.perf_counter()
    futures = []
    results = []
    local_shed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_in_flight) as executor:
        for i, prompt in enumerate(prompts):
            delay = started + i / request_rate - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            # Do not silently queue inside the load generator: disclose local saturation.
            if sum(not f.done() for f in futures) >= max_in_flight:
                local_shed += 1
                continue
            futures.append(executor.submit(request_one, url, prompt, limit))
        results = [f.result() for f in futures]
    duration = time.perf_counter() - started
    passed = [
        r
        for r in results
        if r["status"] == "completed"
        and r["ttft_ms"] is not None
        and r["ttft_ms"] <= ttft_slo_ms
    ]
    return {
        "execution_mode": "live HTTP requests",
        "offered_requests": len(prompts),
        "client_shed_requests": local_shed,
        "duration_s": round(duration, 3),
        "ttft_slo_ms": ttft_slo_ms,
        "ttft_goodput_rps": round(len(passed) / duration, 4),
        "requests": results,
        "limits": "TTFT-only goodput; SSE events are not necessarily model tokens. Client saturation and failed responses are disclosed.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:8766/generate")
    p.add_argument("--requests", type=int, default=6)
    p.add_argument("--rate", type=float, default=1)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    report = run(
        a.url,
        ["Explain how a cache reduces repeated work."] * a.requests,
        request_rate=a.rate,
    )
    with open(a.output, "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
