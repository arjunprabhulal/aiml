"""Check the recorded traces, and replay the recorded model turns through a traced run offline.

Run: python -m unittest -v test_traced.py
The replay uses the model responses stored in the recorded spans; the agent, tools and ADK's
tracing are real, and spans go to an in-memory exporter.
"""
import asyncio
import json
import logging
import os
import re
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
os.environ.pop("OTEL_SDK_DISABLED", None)  # the site's test runner disables the SDK by default

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.telemetry import setup  # noqa: E402
from google.genai import types  # noqa: E402

import traced  # noqa: E402

HERE = Path(__file__).resolve().parent
RECORD = json.loads((HERE / "recorded-runs.json").read_text())
SPANS = [json.loads(line) for line in (HERE / "runs/defaults/traces.jsonl").read_text().splitlines()]
TURNS = [json.loads(s["attributes"]["gcp.vertex.agent.llm_response"])["content"]
         for s in sorted(SPANS, key=lambda s: s["start_time"]) if s["name"] == "call_llm"]
EXPORTER = InMemorySpanExporter()
PROVIDER = TracerProvider()
PROVIDER.add_span_processor(SimpleSpanProcessor(EXPORTER))
trace.set_tracer_provider(PROVIDER)


class ReplayLlm(BaseLlm):
    turns: list

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def replay(capture: str) -> list:
    EXPORTER.clear()
    os.environ["ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"] = capture
    model = ReplayLlm(model="replay", turns=[dict(t) for t in TURNS])
    original = traced.root_agent
    traced.root_agent = original.clone(update={"model": model})
    try:
        answer = asyncio.run(traced.ask(RECORD["question"]))
    finally:
        traced.root_agent = original
    return answer, EXPORTER.get_finished_spans()


def content_attributes(spans) -> list:
    return sorted({f"{s.name}: {k}" for s in spans for k, v in s.attributes.items() if "search index" in str(v)})


def setUpModule():
    warnings.simplefilter("ignore")  # unittest resets the filter; ADK warns about experimental features


class Traces(unittest.TestCase):
    def test_the_recorded_trace_nests_model_and_tool_spans_under_the_agent(self):
        lines = traced.span_tree(HERE / "runs/defaults")
        self.assertTrue(lines[0].startswith("invocation"))
        self.assertTrue(lines[1].startswith("  invoke_agent docs_assistant"))
        nested = [re.split(r"\s{2,}", line.strip())[0] for line in lines[2:] if line[4] != " "]
        self.assertEqual(nested, ["call_llm", "execute_tool list_pages", "call_llm",
                                  "execute_tool read_page", "call_llm"])

    def test_output_tokens_in_spans_include_thinking_tokens(self):
        for span in SPANS:
            if span["name"] == "call_llm":
                usage = json.loads(span["attributes"]["gcp.vertex.agent.llm_response"])["usage_metadata"]
                self.assertEqual(span["attributes"]["gen_ai.usage.output_tokens"],
                                 usage["candidates_token_count"] + usage.get("thoughts_token_count", 0))
                self.assertGreater(usage["thoughts_token_count"], usage["candidates_token_count"])

    def test_by_default_spans_carry_the_prompt_and_tool_results(self):
        answer, spans = replay("true")
        self.assertIn("(cli.md)", answer)
        self.assertEqual(content_attributes(spans), RECORD["runs"]["defaults"]["content_attributes"])

    def test_turning_capture_off_removes_message_content(self):
        answer, spans = replay("false")
        self.assertIn("(cli.md)", answer)
        self.assertEqual(content_attributes(spans), [])
        self.assertEqual(RECORD["runs"]["production"]["content_attributes"], [])

    def test_without_otel_service_name_the_resource_has_no_service_name(self):
        self.assertIsNone(RECORD["runs"]["defaults"]["service_name"])
        os.environ.pop("OTEL_SERVICE_NAME", None)
        self.assertNotIn("service.name", setup._get_otel_resource().attributes)
        os.environ["OTEL_SERVICE_NAME"] = "docs-assistant"
        self.assertEqual(setup._get_otel_resource().attributes["service.name"], "docs-assistant")

    def test_an_otlp_endpoint_without_the_exporter_package_fails_at_startup(self):
        self.assertIn("ModuleNotFoundError", RECORD["runs"]["otlp-without-exporter"]["error"])
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
        try:
            with self.assertRaises(ModuleNotFoundError):
                setup._get_otel_exporters()
        finally:
            del os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]


if __name__ == "__main__":
    unittest.main()
