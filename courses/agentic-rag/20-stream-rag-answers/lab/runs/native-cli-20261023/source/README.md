# Stream RAG Answers

Consume an actual local UTF-8/NDJSON application-frame stream derived from
preserved original Gemma JSON replies. Requires Python 3.12 or later; standard
library only. No inference, provider stream, HTTP service, model/API call,
download, installation or network request runs in this lab.

```sh
python3 run.py --output runs/my-run/result.json
python3 -m unittest discover -v
python3 render_output.py --input runs/my-run/result.json --output /tmp/stream-report.html
```

Run from this directory. Actual results, stdout/stderr, tests, command and source/
environment records live under `runs/2026-10-23-stream/`. Opening the report reads
saved results; it does not execute a model or stream again.

## Preserve the recording and its request

`fixtures/recording.json` is a byte-identical copy of the original complete
recording from `record-a-rag-baseline/runs/20261023T002037.167760Z-fixed-eight-local-baseline/recording.json`.
Its SHA-256 is pinned in code and provenance metadata. The complete file is kept
unchanged, including held-out data; only the four explicitly allowed development
case IDs can select a reply. Held-out responses are not selected or replayed.

`load_binding(case_id)` returns the original exact messages, request SHA, schema,
corpus/index identity and selected source passages/URLs. It verifies the recorded
message digest and selected context. Replaying with a changed prompt, corpus
identity, selected context or request hash is refused. Every frame carries the
canonical binding hash. These are consistency checks against a pinned local
recording, not authentication of arbitrary incoming model content.

## Bytes, frames and model output are different boundaries

The original recording contains **complete model messages**, not provider token
or delta events. The local producer slices their exact raw JSON strings into
13-character `content_delta` frames and adds one local terminal frame. NDJSON
encodes those frames; a generator then fragments their UTF-8 bytes into arbitrary
1/2/7/3/11-byte transport pieces. Neither boundary represents model tokens,
provider chunks or measured generation timing. No latency claim is made.

`StreamConsumer.feed(bytes)` uses a strict incremental UTF-8 decoder and buffers
until newline-delimited JSON frames are complete. It requires exact one-based
sequence numbers, exact frame fields and the bound request identity. Duplicate,
out-of-order, malformed, over-limit or post-terminal frames fail. Total wire
bytes are capped at 65,536, each frame at 8,192 UTF-8 bytes excluding newline,
content at 16,384 Python characters, and frame count at 1,000. These are local
application limits, not model context limits.

## Provisional content is not an accepted answer

Content deltas only append provisional raw JSON content, not parsed answer-text deltas. A local `done` terminal is
necessary, then end-of-body/iterator EOF must arrive with no trailing bytes or partial UTF-8/
frame. Only then does `finish()` parse the complete answer JSON and require the
three fields `status`, `answer`, `source_ids`. Status is `answered` or `not_in_docs`;
answer text must be nonempty; source IDs must be unique strings from the exact
selected context. `answered` requires citations; `not_in_docs` requires none.
URLs and chunk IDs resolve from the bound context, never model-supplied links.

A successful result exposes the accepted answer/citations and a `validated_answer`
event. Until that point there is no such event. Known-context membership and
schema validity do not prove factual correctness or that a citation supports a
claim. The inherited UTF-8-write reply still says `not_in_docs`; it was not repaired
or rerecorded to make this lesson look successful.

The local terminal kinds `error` and `cancel` produce explicit failed/cancelled
results. EOF without a terminal produces `incomplete`; protocol/schema violations
produce `invalid`. All withhold `accepted_answer` and citations while retaining
provisional text for inspection. Cancel/error/truncation and producer-I/O-error examples in this run
are controlled local failure exercises, not recorded provider incidents. The
consumer catches a producer iterator `OSError` as `error` / `transport_io_error`,
retains provisional content, and withholds the answer even after a local done
frame. EOF means end of the input body/iterator, not closing a physical TCP
connection. Cancel is a local protocol terminal, not a provider cancellation API.
Provisional content is exposed as an attribute/events; no UI callback is implemented.
The consumer does not retry, resume, checkpoint or serve an HTTP response.

## Reproducible guards

The tests cover byte-by-byte UTF-8 and JSON splits, EOF before terminal, truncated
UTF-8/NDJSON, duplicate/out-of-order sequence, post-terminal data, invalid/duplicate
JSON keys, invalid schema, unknown citations, exact request binding, limits and
controlled cancel/error. Unicode transport text in one unit test is explicitly a
controlled unit fixture; original complete model replies remain unchanged.

Named failures include `test_valid_json_without_terminal_is_not_accepted`,
`test_no_frames_or_bytes_after_terminal`, `test_unknown_context_citation_refused`,
`test_changed_messages_corpus_or_context_cannot_replay`,
`test_cancel_and_error_withhold_even_complete_json` and
`test_duplicate_out_of_order_and_boolean_sequences_refused`.
