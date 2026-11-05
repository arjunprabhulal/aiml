"""A small span tracer with W3C Trace Context propagation. Python standard library only.

A trace is the tree of spans for one request. Each span has a trace ID shared by
the whole tree, its own span ID, and the span ID of its parent. A process passes
its current span to another process in a `traceparent` header:

    traceparent: 00-<32 hex trace-id>-<16 hex parent-id>-<2 hex flags>

Each process exports its own finished spans to its own JSON Lines file. collect()
reads every file and rebuilds the trees; a span whose parent is in no file is an
orphan, the sign that some hop did not pass the header on.

The clock and the ID source are injected. Tests use a counting clock and IDs
derived from a seed, so every span, ID and duration is the same on every run.
Real use passes time.perf_counter_ns and random IDs, as the W3C recommends.
"""
import hashlib
import json
import re
import secrets
import time
from pathlib import Path

TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
# Fields that describe one run's timing; they change on every rerun with a real clock.
TIMING_FIELDS = ("start_ns", "end_ns", "duration_ms")


def format_traceparent(trace_id, span_id, sampled=True):
    return f"00-{trace_id}-{span_id}-{'01' if sampled else '00'}"


def parse_traceparent(value):
    """Return (trace_id, parent_id) or None. All-zero IDs and other versions are invalid."""
    match = TRACEPARENT.match(value or "")
    if not match or set(match[1]) == {"0"} or set(match[2]) == {"0"}:
        return None
    return match[1], match[2]


class RandomIds:
    """IDs as the W3C recommends: random, so they are unique and reveal nothing."""

    def trace_id(self):
        return secrets.token_hex(16)

    def span_id(self):
        return secrets.token_hex(8)


class DerivedIds:
    """Reproducible IDs for recorded fixtures: SHA-256 of a seed and a counter."""

    def __init__(self, seed):
        self.seed, self.count = seed, 0

    def _next(self, length):
        self.count += 1
        return hashlib.sha256(f"{self.seed}:{self.count}".encode()).hexdigest()[:length]

    def trace_id(self):
        return self._next(32)

    def span_id(self):
        return self._next(16)


class CountingClock:
    """A fake monotonic clock: each reading is `step` nanoseconds after the last."""

    def __init__(self, step=1_000_000):
        self.now, self.step = 0, step

    def __call__(self):
        self.now += self.step
        return self.now


class Span:
    def __init__(self, tracer, name, trace_id, parent_id, attributes):
        self.tracer, self.name = tracer, name
        self.trace_id, self.span_id, self.parent_id = trace_id, tracer.ids.span_id(), parent_id
        self.attributes, self.events, self.status = dict(attributes), [], "ok"
        self.start_ns = tracer.clock()

    def set(self, **attributes):
        self.attributes.update(attributes)

    def event(self, name, **attributes):
        self.events.append({"name": name, **attributes})

    def traceparent(self):
        return format_traceparent(self.trace_id, self.span_id)

    def __enter__(self):
        self.tracer.stack.append(self)
        return self

    def __exit__(self, kind, error, traceback):
        self.tracer.stack.pop()
        if error is not None:
            self.status = "error"
            self.attributes["error.type"] = kind.__name__
        end_ns = self.tracer.clock()
        self.tracer.export({
            "trace_id": self.trace_id, "span_id": self.span_id, "parent_id": self.parent_id,
            "service": self.tracer.service, "name": self.name, "status": self.status,
            "attributes": self.attributes, "events": self.events,
            "start_ns": self.start_ns, "end_ns": end_ns, "duration_ms": round((end_ns - self.start_ns) / 1e6, 3),
        })
        return False  # never swallow the error


class Tracer:
    """Starts spans for one service and appends each finished span to its exporter."""

    def __init__(self, service, exporter, clock=time.perf_counter_ns, ids=None):
        self.service, self.export, self.clock = service, exporter, clock
        self.ids = ids or RandomIds()
        self.stack = []

    def span(self, name, traceparent=None, **attributes):
        """A child of the current span; else of an incoming traceparent; else a new trace."""
        if self.stack:
            parent = self.stack[-1]
            return Span(self, name, parent.trace_id, parent.span_id, attributes)
        incoming = parse_traceparent(traceparent)
        if incoming:
            return Span(self, name, incoming[0], incoming[1], attributes)
        span = Span(self, name, self.ids.trace_id(), None, attributes)
        if traceparent is not None:
            span.event("invalid traceparent ignored; trace restarted")
        return span


class JsonLinesExporter:
    """Appends one JSON object per finished span to a file, as a collector would receive them."""

    def __init__(self, path):
        self.path = Path(path)

    def __call__(self, span):
        with self.path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(span, sort_keys=True) + "\n")


def read_spans(*paths):
    spans = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                spans.append(json.loads(line))
    return spans


def collect(spans):
    """Group spans by trace and nest them. Return {trace_id: {"roots": [...], "orphans": [...]}}."""
    traces = {}
    for span in spans:
        traces.setdefault(span["trace_id"], []).append(span)
    result = {}
    for trace_id, members in traces.items():
        by_id = {span["span_id"]: dict(span, children=[]) for span in members}
        roots, orphans = [], []
        for span in sorted(by_id.values(), key=lambda s: (s["start_ns"], s["span_id"])):
            if span["parent_id"] is None:
                roots.append(span)
            elif span["parent_id"] in by_id:
                by_id[span["parent_id"]]["children"].append(span)
            else:
                orphans.append(span)  # its parent was never exported: a broken hop
        result[trace_id] = {"roots": roots, "orphans": orphans}
    return result


def walk(node, depth=0):
    """Yield (depth, span) in tree order."""
    yield depth, node
    for child in node["children"]:
        yield from walk(child, depth + 1)


def without_timing(value):
    """A copy without TIMING_FIELDS, for comparing a rerun with a record."""
    if isinstance(value, dict):
        return {k: without_timing(v) for k, v in value.items() if k not in TIMING_FIELDS}
    if isinstance(value, list):
        return [without_timing(v) for v in value]
    return value
