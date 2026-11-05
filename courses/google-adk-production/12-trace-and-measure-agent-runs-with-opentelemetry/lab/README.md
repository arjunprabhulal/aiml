# Trace and measure agent runs with OpenTelemetry

Use the entire extracted lab directory, including docs, fixtures and tests. Python 3.12+ is required. Install the pinned environment with `python -m pip install -r requirements-lock.txt` in your own virtual environment. These instructions do not provision resources.

## Run a fresh interaction

Set `GOOGLE_API_KEY` in your environment before running the command. Do not put the key in source files or output captures. Run from this directory:

```sh
python traced.py "How do I rebuild the search index?" telemetry
```

traced.py attaches file exporters before starting its Runner. It writes telemetry/traces.jsonl and metrics.jsonl; a bare agent launch does not register these exporters. No collector is required. Do not set OTEL_EXPORTER_OTLP_ENDPOINT unless you intend to send telemetry to your own collector. The supplied runs/ data is historical, not a fresh execution.

These commands make fresh model requests and may incur provider charges. They are instructions for a learner's intentional run, not a claim that this repair executed a new model run. The lesson describes the existing saved recordings separately.

## Verify offline

```sh
python -m unittest -v test_traced.py
```

These tests use saved records, replay models or deterministic local checks. Passing them does not establish current model behavior. Historical `test-output.txt` is retained; new regression tests can increase the current test count.

## Preserve the supplied evidence

`record.py` runs a multi-case fresh-model experiment and overwrites saved output/results. Use a separate copy before running it. Supplied raw records and original media, where present, are historical evidence. An offline report view is not a fresh model execution. See the article for the mechanism, observed failures and official references.

## Selected fresh run, October 23, 2026

See `runs/live-2026-10-23/run.json`, original `actual-terminal.png`, per-request ledger and receipts. This used the lesson App/Runner/services, not the native ADK CLI or Web UI. passed: actual local invocation/model/tool spans and metrics, service docs-assistant, message capture disabled. passed for selected question: docs-assistant index --rebuild, citing cli.md This bounded run used 3 requests capped at 1024 output tokens each, with no reruns. Historical recordings remain unchanged. Public JSON omits only opaque thought-signature fields; private originals are retained.
