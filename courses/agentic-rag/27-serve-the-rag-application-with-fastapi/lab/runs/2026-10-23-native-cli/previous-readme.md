# Serve the RAG Application with FastAPI

Expose the existing bounded scripted retrieval controller through a real local
HTTP boundary. This endpoint returns retrieval traces and validated passages; it
does not generate answers or run a model. The recorded run uses the prepared
Python 3.12 environment and exact installed SDK versions in `requirements.txt` /
`requirements.lock`. Older-runtime compatibility was not tested. No installation,
new package, model, download or external API request is needed for this run.

From this directory, with that prepared environment selected:

```sh
python3 run.py --output runs/my-run/result.json
python3 -m unittest discover -v
python3 render_output.py --input runs/my-run/result.json --output /tmp/http-report.html
```

For a manual local server:

```sh
python3 -m uvicorn api:app --host 127.0.0.1 --port 8000
```

The demo and tests start actual Uvicorn subprocesses on prebound loopback sockets
and send real HTTP requests with HTTPX. They also use TestClient for targeted
in-process lifecycle/fault tests; TestClient is not the only execution evidence.
Actual response bodies, subprocess logs, stdout/stderr, commands, environment and
source hashes are under `runs/2026-10-23-http/`. Opening the saved HTML report does
not run a server or make a request again.

## API contract

`GET /health` returns status `ok`, offline mode and corpus ID only after lifespan
startup loads and validates the pinned corpus. Shutdown clears readiness and the
snapshot. This is local application readiness, not an upstream dependency or load
check. Swagger/ReDoc pages are disabled; no CDN UI resources are requested.

`POST /retrieve` accepts exactly `application/json` (an optional charset parameter
is accepted). Required field `question` is a nonblank string of at most 512
characters. `version` defaults to `3.12`, numeric major.minor syntax, at most 16
characters. Limits default to steps/searches/reads/source bytes `6/2/2/4096`;
accepted ranges are `0–12 / 0–3 / 0–3 / 0–4096`. Integers are strict: Booleans,
strings and fractions do not coerce. Extra fields fail. Zero limits are useful
for demonstrating denial before a tool action.

The ASGI middleware counts body bytes before JSON parsing, including bodies
without Content-Length. It refuses more than 4,096 bytes before copying an
over-limit fragment into its buffer. This is an application body bound, not a
hard process-memory or socket-buffer guarantee. Duplicate JSON keys, nonfinite
constants, malformed JSON and invalid UTF-8 fail safely.

```json
{"question":"Will write_text replace the contents of an existing file?"}
```

A fresh `DocumentationTools` instance is created per request and closed in
`finally`. Issued passage handles do not share mutable receipt state across HTTP
requests. The core `tools.py`, `refine.py`, `limits.py`, BM25 implementation,
validator, loader and corpus are copied unchanged from the preceding limits lab.
No new embeddings or fresh answers are produced for a changed context.

## Interpret the response and statuses

A valid request can return HTTP 200 with `completed`, `incomplete` or `limited`.
`completed` means the handwritten controller found its configured literal passage
marker, not that an answer is correct. `incomplete` includes empty eligible
versions and unmatched rewrite rules. `limited` retains the denied action and
usage counters; limits apply before invocation through the copied admission core.
`admission.accepted` means the HTTP request passed validation, not that every
proposed tool action was admitted.

Responses include the canonical request, corpus ID, deterministic request ID,
status/reason, declared limits, usage, trace, policy and exact validated read
payloads in `evidence`. No answer field is returned. The request ID hashes
`{"request": validated_payload_with_defaults, "corpus_id": corpus_id}` using
sorted compact JSON and UTF-8 with ensure_ascii=False. It identifies request
content, not a unique execution. The result digest binds the complete projection.
`validate_response()` checks saved-response/request consistency; hashes are not
network authentication or proof of citation support. Successful and failed
retrieval responses also carry `X-Retrieval-Body-SHA256`, computed from the actual
serialized response body. A browser can hash its fetched UTF-8 text before parsing
JSON, avoiding float-serialization differences. This is a consistency check, not
authentication; error envelopes without a retrieval projection do not carry it.

HTTP errors are stable: `422` invalid request/JSON, `413` body too large, `415`
unsupported media, `503` controlled retrieval failure or not-ready, and generic
`500` for an unexpected application error. Validation issues contain bounded
field paths/types without input values. Tool exception details are removed from
public traces. Successful reads retain corpus/search/read IDs, current source and
chunk hashes, versions and spans; the service verifies them before projection.

## Reproduce a controlled failure without a public fault switch

`create_app(tool_factory=DocumentationTools)` supports trusted local construction.
`fault_fixture:app` injects a deliberate exception after a real native search.
The HTTP API has no fault argument. Its run returns 503, preserves reserved
attempt accounting, withholds nonexistent evidence and does not expose the
private exception text. This is a controlled fixture, not a production incident.

The harness sends SIGTERM for shutdown and records the raw child exit status.
The installed Uvicorn version re-raises that signal after graceful shutdown, so
`-15` accompanies logs showing application shutdown complete. The harness records
both lifecycle observation and that the child was reaped; it does not rewrite
that status to zero.

Named checks include `test_chunked_body_bound_without_content_length`,
`test_strict_request_invalid_types_extra_fields_and_surrogate`,
`test_malformed_duplicate_json_and_nonfinite_are_safe_422`,
`test_limits_deny_before_read_and_keep_admission_usage`,
`test_response_request_and_digest_tampering_refused`, and
`test_real_http_controlled_tool_failure_503_no_private_error_leak`.

This is a loopback teaching application. Authentication, CORS configuration,
production deployment, concurrency/capacity, latency and model-answer quality
were not demonstrated. Original Python summaries and their fact-status limits
remain unchanged; the Python 3.13 API description is not executed here.

Official documentation: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
[error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/), and
[Pydantic configuration](https://docs.pydantic.dev/latest/api/config/).
