"""Run the docs assistant with OpenTelemetry traces and metrics written to local files.

Run from this folder: python traced.py "QUESTION" [OUT_DIR]
Writes OUT_DIR/traces.jsonl (one span per line) and OUT_DIR/metrics.jsonl, then prints
the span tree and the metric totals. With OTEL_EXPORTER_OTLP_ENDPOINT set, ADK also adds
OTLP exporters to the same providers, so a collector such as Jaeger gets the same spans.
"""
import asyncio
import warnings
import json
import sys
from pathlib import Path

warnings.filterwarnings("ignore")

from opentelemetry import metrics, trace  # noqa: E402
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from google.adk.runners import InMemoryRunner
from google.adk.telemetry.setup import OTelHooks, maybe_set_otel_providers
from google.genai import types

from docs_assistant.agent import root_agent


def set_up_telemetry(out: Path) -> None:
    """Register file exporters for spans and metrics on new global providers."""
    out.mkdir(parents=True, exist_ok=True)
    spans = ConsoleSpanExporter(out=(out / "traces.jsonl").open("w"),
                                formatter=lambda span: span.to_json(indent=None) + "\n")
    points = ConsoleMetricExporter(out=(out / "metrics.jsonl").open("w"),
                                   formatter=lambda data: data.to_json(indent=None) + "\n")
    maybe_set_otel_providers([OTelHooks(
        span_processors=[SimpleSpanProcessor(spans)],
        # Export once, at force_flush, instead of every 60 seconds.
        metric_readers=[PeriodicExportingMetricReader(points, export_interval_millis=3_600_000)],
    )])


async def ask(question: str) -> str:
    runner = InMemoryRunner(agent=root_agent, app_name="docs_assistant")
    session = await runner.session_service.create_session(app_name="docs_assistant", user_id="dev")
    message = types.Content(role="user", parts=[types.Part(text=question)])
    answer = ""
    async for event in runner.run_async(user_id="dev", session_id=session.id, new_message=message):
        if event.is_final_response() and event.content:
            answer = "".join(part.text or "" for part in event.content.parts if not part.thought)
    return answer


def span_tree(out: Path) -> list[str]:
    """One line per span, indented under its parent, with duration and the attributes that matter."""
    spans = [json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()]
    children: dict = {}
    for span in spans:
        children.setdefault(span["parent_id"], []).append(span)
    keep = ("gen_ai.request.model", "gen_ai.tool.name", "gen_ai.usage.input_tokens",
            "gen_ai.usage.output_tokens", "error.type")
    lines = []

    def walk(parent, depth):
        for span in sorted(children.get(parent, []), key=lambda s: s["start_time"]):
            ms = (_ns(span["end_time"]) - _ns(span["start_time"])) / 1e6
            attrs = " ".join(f"{k.split('.')[-1]}={v}" for k, v in span["attributes"].items() if k in keep)
            lines.append(f"{'  ' * depth}{span['name']:<{40 - 2 * depth}} {ms:8.1f} ms  {attrs}".rstrip())
            walk(span["context"]["span_id"], depth + 1)

    walk(None, 0)
    return lines


def _ns(iso: str) -> int:
    from datetime import datetime
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1e9)


def metric_totals(out: Path) -> list[str]:
    lines = []
    for line in (out / "metrics.jsonl").read_text().splitlines():
        for resource in json.loads(line)["resource_metrics"]:
            for scope in resource["scope_metrics"]:
                for metric in scope["metrics"]:
                    for point in metric["data"]["data_points"]:
                        labels = ",".join(f"{v}" for k, v in point["attributes"].items()
                                          if k in ("gen_ai.agent.name", "gen_ai.tool.name", "gen_ai.token.type"))
                        unit = "" if metric["unit"] == "1" else f" {metric['unit']}"  # "1" means a plain count
                        lines.append(f"{metric['name']:<42} {labels:<24} count={point.get('count', '-')} "
                                     f"sum={round(point.get('sum', point.get('value', 0)), 3)}{unit}")
    return lines


if __name__ == "__main__":
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "telemetry")
    set_up_telemetry(out)
    print("answer:", asyncio.run(ask(sys.argv[1])))
    trace.get_tracer_provider().force_flush()
    metrics.get_meter_provider().force_flush()
    print("\n".join(["", "spans:", *span_tree(out), "", "metrics:", *metric_totals(out)]))
