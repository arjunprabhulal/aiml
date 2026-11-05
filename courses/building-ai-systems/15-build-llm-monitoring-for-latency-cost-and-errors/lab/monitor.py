"""Monitor a simulated support service: latency, tokens, cost, errors and queue depth, with alert rules.

    python3 monitor.py            # print one line per window and every alert change
    python3 monitor.py --check    # also compare with the saved monitoring.json
    python3 monitor.py --write    # save a fresh run as monitoring.json

Standard library only. Nothing is timed: the clock is simulated milliseconds. Requests
arrive as traffic.json describes and wait in one queue for one model worker. Each
request's tokens and model time come from a call recorded from gemma4:e2b in the
tracing build (calls.json), taken in turn; traffic.json can slow the model for a
phase. A client gives up after its timeout, but the worker still finishes the call.

Every request is reported in the 60-second window in which the client saw it end:
its reply, its timeout, or its 503. Latency histograms use the OpenTelemetry GenAI
duration buckets, and the p95 is estimated from them the way Prometheus's
histogram_quantile does; the exact p95 is reported beside it.
"""
import argparse
import bisect
import json
import math
import sys
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRAFFIC = json.loads((HERE / "traffic.json").read_text(encoding="utf-8"))
CALLS = json.loads((HERE / "calls.json").read_text(encoding="utf-8"))["calls"]
RULES = json.loads((HERE / "alerts.json").read_text(encoding="utf-8"))["rules"]
PRICES = json.loads((HERE / "prices.json").read_text(encoding="utf-8"))
# ExplicitBucketBoundaries for gen_ai.client.inference.duration, in seconds.
BUCKETS_S = (0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92)


class Histogram:
    """Counts per explicit bucket; bucket i holds values v with BUCKETS[i-1] < v <= BUCKETS[i]."""

    def __init__(self, bounds):
        self.bounds, self.counts = tuple(bounds), [0] * (len(bounds) + 1)  # the last bucket is +Inf

    def record(self, value):
        self.counts[bisect.bisect_left(self.bounds, value)] += 1

    def quantile(self, q):
        """Estimate a quantile by linear interpolation inside its bucket, as histogram_quantile does.

        The lowest bucket starts at 0. A quantile in the +Inf bucket returns the highest finite bound.
        """
        total = sum(self.counts)
        if total == 0:
            return None
        rank, seen = q * total, 0
        for i, count in enumerate(self.counts):
            if count and seen + count >= rank:
                if i == len(self.bounds):
                    return self.bounds[-1]
                lower = self.bounds[i - 1] if i else 0.0
                return lower + (self.bounds[i] - lower) * (rank - seen) / count
            seen += count
        return self.bounds[-1]


def nearest_rank(values, p):
    ordered = sorted(values)
    return ordered[-(-p * len(ordered) // 100) - 1] if ordered else None


def arrivals():
    """Evenly spaced arrivals per phase, each with the model slowdown that applies to it."""
    out, start = [], 0
    for phase in TRAFFIC["phases"]:
        length_ms = phase["seconds"] * 1000
        count = phase["requests_per_minute"] * phase["seconds"] // 60
        out += [(start + length_ms * i // count, phase["model_slowdown"]) for i in range(count)]
        start += length_ms
    return out, start


def simulate(config):
    """One worker, one bounded queue. Return one row per request, in arrival order."""
    limit, timeout, drop = config["queue_limit"], TRAFFIC["client_timeout_ms"], config["drop_expired"]
    plan, _ = arrivals()
    rows, waiting, free_at = [], deque(), 0
    for i, (at, slowdown) in enumerate(plan):
        call = CALLS[i % len(CALLS)]
        # Start every waiting request the worker can begin before this arrival.
        while waiting and max(free_at, waiting[0]["arrival_ms"]) <= at:
            free_at = start(waiting.popleft(), free_at, timeout, drop)
        depth = len(waiting) + (1 if free_at > at else 0)  # requests in the system, including the one running
        row = {"n": i, "arrival_ms": at, "input_tokens": call["input_tokens"],
               "output_tokens": call["output_tokens"], "model_ms": round(call["model_ms"] * slowdown, 3),
               "depth_at_arrival": depth}
        if len(waiting) >= limit:
            row.update(status="503", end_ms=at, latency_ms=0, wait_ms=0, ran=False)
        else:
            waiting.append(row)
        rows.append(row)
    while waiting:
        free_at = start(waiting.popleft(), free_at, timeout, drop)
    return rows


def start(row, free_at, timeout, drop_expired):
    """Run one request on the worker. The client stops waiting at its timeout.

    With drop_expired, the worker skips a request whose client gave up while it waited;
    without it, the worker spends the model call anyway.
    """
    begin = max(free_at, row["arrival_ms"])
    deadline = row["arrival_ms"] + timeout
    if drop_expired and begin >= deadline:
        row.update(status="timeout", end_ms=deadline, latency_ms=timeout, wait_ms=timeout, ran=False)
        return free_at
    finish = begin + row["model_ms"]
    row.update(wait_ms=begin - row["arrival_ms"], ran=True)
    if finish <= deadline:
        row.update(status="ok", end_ms=finish, latency_ms=round(finish - row["arrival_ms"], 3))
    else:
        row.update(status="timeout", end_ms=deadline, latency_ms=timeout)
    return finish


def cost_usd(input_tokens, output_tokens):
    """Example prices from prices.json; the local model itself has no per-token price."""
    return round(math.fsum([input_tokens * PRICES["input_usd_per_million"],
                            output_tokens * PRICES["output_usd_per_million"]]) / 1e6, 6)


def windows(rows, duration_ms):
    size = TRAFFIC["window_seconds"] * 1000
    out = []
    for w in range(math.ceil(duration_ms / size)):
        lo, hi = w * size, (w + 1) * size
        done = [r for r in rows if lo <= r["end_ms"] < hi]
        answered = [r for r in done if r["status"] == "ok"]
        histogram = Histogram(BUCKETS_S)
        for r in answered:
            histogram.record(r["latency_ms"] / 1000)
        errors = {status: sum(r["status"] == status for r in done) for status in ("503", "timeout")}
        # Tokens and model time are counted for every call the worker ran that ended here,
        # including calls whose client had already given up.
        ran = [r for r in rows if r["ran"] and lo <= r["arrival_ms"] + r["wait_ms"] + r["model_ms"] < hi]
        estimate = histogram.quantile(0.95)
        out.append({
            "window": w, "start_s": lo // 1000,
            "arrivals": sum(lo <= r["arrival_ms"] < hi for r in rows),
            "ended": len(done), "ok": len(answered), "errors": errors,
            "error_rate": round(sum(errors.values()) / len(done), 4) if done else 0.0,
            "latency_ms": {"p50": nearest_rank([r["latency_ms"] for r in answered], 50),
                           "p95": nearest_rank([r["latency_ms"] for r in answered], 95),
                           "p95_from_buckets": None if estimate is None else round(estimate * 1000, 1),
                           "bucket_counts": histogram.counts},
            "max_queue_depth": max((r["depth_at_arrival"] for r in rows if lo <= r["arrival_ms"] < hi), default=0),
            "input_tokens": sum(r["input_tokens"] for r in ran),
            "output_tokens": sum(r["output_tokens"] for r in ran),
            "cost_usd": cost_usd(sum(r["input_tokens"] for r in ran), sum(r["output_tokens"] for r in ran)),
            "model_ms": round(math.fsum(r["model_ms"] for r in ran), 3),
            "wasted_model_ms": round(math.fsum(r["model_ms"] for r in ran if r["status"] == "timeout"), 3),
        })
    return out


def metric(window, name):
    """Read a rule's metric from one window, such as latency_ms.p95_from_buckets."""
    value = window
    for part in name.split("."):
        value = value[part]
    return value


def evaluate(windows_, rules=RULES):
    """Alert states per window, like Prometheus: pending while the condition holds for fewer
    than `for_windows` evaluations, firing after that, inactive as soon as it stops holding."""
    timeline, changes = [], []
    held = {rule["name"]: 0 for rule in rules}
    state = {rule["name"]: "inactive" for rule in rules}
    for window in windows_:
        row = {"window": window["window"]}
        for rule in rules:
            value = metric(window, rule["metric"])
            met = value is not None and value >= rule["threshold"]
            held[rule["name"]] = held[rule["name"]] + 1 if met else 0
            new = "inactive" if not met else "firing" if held[rule["name"]] >= rule["for_windows"] else "pending"
            if new != state[rule["name"]]:
                changes.append({"window": window["window"], "rule": rule["name"], "from": state[rule["name"]],
                                "to": new, "value": value})
            state[rule["name"]] = row[rule["name"]] = new
        timeline.append(row)
    return timeline, changes


def run(config):
    rows = simulate(config)
    _, duration = arrivals()
    per_window = windows(rows, duration)
    timeline, changes = evaluate(per_window)
    totals = {status: sum(r["status"] == status for r in rows) for status in ("ok", "503", "timeout")}
    return {"name": config["name"], "label": config["label"], "requests": len(rows), "totals": totals,
            "model_calls": sum(r["ran"] for r in rows),
            "wasted_model_ms": round(math.fsum(r["model_ms"] for r in rows if r["ran"] and r["status"] == "timeout"), 3),
            "windows": per_window, "alerts": timeline, "alert_changes": changes}


def results():
    return {"traffic": "traffic.json", "calls": "calls.json", "runs": [run(c) for c in TRAFFIC["configs"]]}


def record(data):
    return json.dumps(data, indent=2) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="compare with the saved monitoring.json")
    parser.add_argument("--write", action="store_true", help="save a fresh run as monitoring.json")
    options = parser.parse_args(argv)
    fresh = results()
    for one in fresh["runs"]:
        report(one)
    if options.write:
        (HERE / "monitoring.json").write_text(record(fresh), encoding="utf-8")
        print("wrote monitoring.json")
    if options.check:
        if (HERE / "monitoring.json").read_text(encoding="utf-8") != record(fresh):
            sys.exit("monitoring.json differs from a fresh run")
        print("monitoring.json matches")


def report(fresh):
    print(f"{fresh['name']}: {fresh['label']}: {fresh['totals']}, model calls {fresh['model_calls']}, "
          f"wasted model ms {fresh['wasted_model_ms']}")
    for w in fresh["windows"]:
        print(f"{w['start_s']:>4}s arrivals {w['arrivals']:>3} ok {w['ok']:>3} 503 {w['errors']['503']:>3} "
              f"timeout {w['errors']['timeout']:>3} err {w['error_rate']:.3f} p95 {w['latency_ms']['p95']} "
              f"(buckets {w['latency_ms']['p95_from_buckets']}) depth {w['max_queue_depth']:>2} "
              f"out-tokens {w['output_tokens']:>5} ${w['cost_usd']:.6f}")
    for change in fresh["alert_changes"]:
        print(f"window {change['window']}: {change['rule']} {change['from']} -> {change['to']} ({change['value']})")


if __name__ == "__main__":
    main()
