"""Evaluate the served model through its HTTP interface and record the results.

Run: python3 evaluate_service.py          (print the report; under a minute on a laptop CPU)
     python3 evaluate_service.py --write  (rewrite eval-report.json and service-time.json)
     python3 evaluate_service.py --check  (exit 1 if eval-report.json differs)
service-time.json holds request latencies from the --write run and is not compared.
"""
import json
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import generate as g
import make_corpus
import kv_cache as kv
import server
import train as t

HERE = Path(__file__).parent
FRESH_SEED, FRESH_STORIES = 2027, 60  # a second set, generated for this build after training ended


def story_checks(base, openings):
    checks = {"well_formed": 0, "keeps_color_and_object": 0}
    for opening in openings:
        code, reply = call(base, "POST", "/generate", {"prompt": opening})
        if code != 200:
            raise RuntimeError(f"service returned {code} for {opening!r}: {reply}")
        result = g.follows_story(opening, reply["text"])
        checks = {k: checks[k] + result[k] for k in checks}
    return checks


def call(base, method, path, body=None, raw=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


ERROR_CASES = [
    ("not JSON", "POST", "/generate", None, b"mia has"),
    ("missing prompt", "POST", "/generate", {"temperature": 1.0}, None),
    ("unknown field", "POST", "/generate", {"prompt": "mia", "top_p": 0.9}, None),
    ("temperature as text", "POST", "/generate", {"prompt": "mia", "temperature": "hot"}, None),
    ("negative temperature", "POST", "/generate", {"prompt": "mia", "temperature": -1}, None),
    ("max_new_tokens too large", "POST", "/generate", {"prompt": "mia", "max_new_tokens": 500}, None),
    ("empty prompt", "POST", "/generate", {"prompt": ""}, None),
    ("body over the size limit", "POST", "/generate", None, json.dumps({"prompt": "mia " * 2000}).encode()),
    ("unknown route", "GET", "/models", None, None),
]


def run():
    service = server.Service()
    srv = server.start(service=service)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        _, _, test = t.split_stories((HERE / "corpus.txt").read_text())
        openings = [s.split(". ")[0] + "." for s in test]
        status, health = call(base, "GET", "/health")
        matches, checks, latencies = 0, {"well_formed": 0, "keeps_color_and_object": 0}, []
        for opening in openings:
            start = time.perf_counter()
            code, reply = call(base, "POST", "/generate", {"prompt": opening})
            latencies.append(time.perf_counter() - start)
            if code != 200:
                raise RuntimeError(f"service returned {code} for {opening!r}: {reply}")
            direct = kv.generate_cached(service.params, service.tok, opening)
            matches += reply["text"] == direct["text"] and reply["stopped"] == direct["stopped"]
            result = g.follows_story(opening, reply["text"])
            checks = {k: checks[k] + result[k] for k in checks}
        errors = []
        for name, method, path, body, raw in ERROR_CASES:
            code, reply = call(base, method, path, body, raw)
            errors.append({"case": name, "status": code, "error": reply.get("error")})
        corpus_text = (HERE / "corpus.txt").read_text()
        known = set(corpus_text.split("\n"))
        fresh_all = [s + "\n" for s in make_corpus.corpus(FRESH_SEED, FRESH_STORIES).split("\n") if s]
        fresh = [s for s in fresh_all if s.rstrip("\n") not in known]
        fresh_openings = [s.split(". ")[0] + "." for s in fresh]
        fresh_encoded = t.encode_all(service.tok, fresh, t.CONFIG["max_len"])
        te = t.encode_all(service.tok, test, t.CONFIG["max_len"])
        report = {
            "health": {"status": status, **health},
            "test_stories": len(openings),
            "served_equals_direct": matches,
            "greedy_story_checks": checks,
            "test_loss": round(t.mean_loss(service.params, te), 4),
            "fresh_set": {"seed": FRESH_SEED, "generated": len(fresh_all), "duplicates_removed": len(fresh_all) - len(fresh),
                          "stories": len(fresh), "test_loss": round(t.mean_loss(service.params, fresh_encoded), 4),
                          "greedy_story_checks": story_checks(base, fresh_openings),
                          "color_recall": t.color_recall(service.params, service.tok, fresh)},
            "color_recall_test": t.color_recall(service.params, service.tok, test),
            "error_cases": errors,
        }
        timing = {"requests": len(latencies), "median_ms": round(1000 * statistics.median(latencies), 1),
                  "max_ms": round(1000 * max(latencies), 1), "python": platform.python_version(),
                  "machine": platform.machine(), "system": platform.system()}
        return report, timing
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    report, timing = run()
    text = json.dumps(report, indent=1) + "\n"
    if "--write" in sys.argv:
        (HERE / "eval-report.json").write_text(text)
        (HERE / "service-time.json").write_text(json.dumps(timing, indent=1) + "\n")
    elif "--check" in sys.argv:
        sys.exit(0 if (HERE / "eval-report.json").read_text() == text else "eval-report.json is out of date")
    else:
        print(text, end="")
