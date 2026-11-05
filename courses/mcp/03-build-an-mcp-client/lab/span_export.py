"""Write this process's OpenTelemetry spans to a JSON Lines file, and join two files into one trace tree."""
import json
import os
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult


class JsonLinesExporter(SpanExporter):
    def __init__(self, path):
        self.path = path

    def export(self, spans):
        with open(self.path, "a", encoding="utf-8") as out:
            for span in spans:
                out.write(json.dumps({
                    "name": span.name, "kind": span.kind.name, "status": span.status.status_code.name,
                    "trace_id": format(span.context.trace_id, "032x"), "span_id": format(span.context.span_id, "016x"),
                    "parent_id": format(span.parent.span_id, "016x") if span.parent else None,
                    "start": span.start_time, "attributes": dict(span.attributes or {})}) + "\n")
        return SpanExportResult.SUCCESS


_exporter = None


def configure(path):
    """Send this process's spans to `path`. A later call only changes the file."""
    global _exporter
    if _exporter is None:
        os.environ["OTEL_SDK_DISABLED"] = "false"  # the repository's test runner disables OpenTelemetry; this exporter only writes a file
        _exporter = JsonLinesExporter(path)
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_exporter))
        trace.set_tracer_provider(provider)
    _exporter.path = path


def span_tree(*paths):
    """Nest the spans from every file by parent, without IDs and times, so two runs compare equal."""
    spans = sorted((json.loads(line) for path in paths for line in Path(path).read_text().splitlines()), key=lambda s: s["start"])
    ids = {s["span_id"] for s in spans}

    def node(span):
        attributes = {k: v for k, v in span["attributes"].items() if k != "jsonrpc.request.id"}
        children = [node(s) for s in spans if s["parent_id"] == span["span_id"]]
        return {"name": span["name"], "kind": span["kind"], "status": span["status"], "attributes": attributes, "children": children}

    return {"traces": len({s["trace_id"] for s in spans}), "spans": len(spans),
            "roots": [node(s) for s in spans if s["parent_id"] not in ids]}
