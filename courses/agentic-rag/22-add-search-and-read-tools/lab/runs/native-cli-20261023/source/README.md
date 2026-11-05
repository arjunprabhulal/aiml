# Add Search and Read Tools

Expose actual local documentation search and exact passage reads as two small
Python tool functions. Requires Python 3.11 or later with SQLite FTS5; no packages,
model calls, downloads or network. Run from this directory:

```sh
python3 run.py --output runs/my-run/result.json
python3 -m unittest discover -v
python3 render_output.py --input runs/my-run/result.json --output /tmp/tools-report.html
```

The recorded run is `runs/2026-10-23-tools/`, including complete results, stdout,
stderr, tests, commands and source/environment hashes. The report displays saved
results; opening it does not execute a tool again. No model selects these calls.

## Search returns handles, read resolves their contents

`DocumentationTools(load_snapshot()).search(query, k=2, version='3.12')` returns
a bounded metadata envelope and passage handles, not passage text. Each handle
binds current corpus ID, search request ID, current passage ID, source ID/version,
source revision, source/chunk hashes, inclusive line span, UTF-8 passage byte count,
native score and rank. `read_token` is a deterministic receipt digest, not a secret
or authorization credential. Search metadata is intentionally visible to callers.

`read(handle)` accepts only an exact issued handle from a known search receipt for
the current corpus. It returns the exact passage text and bound source URL, with
a read request ID and result digest. Unknown passage IDs, stale corpus IDs,
unissued receipts and changed/rehashed handles fail. `validate_read(result, handle)`
compares the full result with the current authoritative payload, rejecting even
rehashed text/URL/version edits. Reads cannot open arbitrary paths or URLs.

`validate_handle(handle)` and `read_cost(handle)` validate receipt metadata without
calling read or exposing passage text. `byte_count` measures normalized passage
text encoded in UTF-8, not JSON framing/metadata overhead. These helpers let the
later limits lesson check a source-byte budget before executing read.

## Native retrieval and explicit boundaries

The native SQLite FTS5 `bm25()` implementation is copied unchanged from How BM25
Ranks Documents, together with its snapshot validator and loader. The original
four Python API summaries and current chunk IDs come from the pinned Module4
snapshot; the complete snapshot file is hash checked. Existing fact status,
source versions and normalized-text provenance remain unchanged. The Python 3.13
summary remains documented only, not executed by this lab.

Query accepts one ASCII alphanumeric indexed term, at most 64 characters. Empty
queries, query syntax, paths and URLs fail. k is a non-Boolean integer from 1–10;
version must have numeric major.minor form. An absent term or version with no
eligible matches returns an empty result list. The corpus is capped at 100
passages; search fetches all native ranks within that bound, applies version
eligibility, then applies k. Scores use global corpus statistics. This is an
in-memory teaching index, not a design for an unbounded search service.

The recorded `overwritten` query returns one current `path-write` handle. Read
resolves its original summary. A version-edited handle is refused, while a no-hit
query and an ineligible version both return empty results.

Hashes and receipts check consistency; they do not prove facts, citation support,
permissions or trust in a caller who controls program internals. No sandbox or
permission system is implemented. Closed tool instances refuse later actions.

## Verify the failures

The 12 tests include `test_unknown_stale_or_unissued_handles_refused`,
`test_changed_or_rehashed_handle_refused`,
`test_changed_read_payload_even_rehashed_refused`,
`test_invalid_queries_k_versions_and_unknown_arguments_refused` and
`test_preflight_cost_does_not_invoke_read`.

`fixtures/development-cases.json` preserves the earlier development set for later
comparison. Its historical target chunk IDs are not the current snapshot IDs;
this lab never substitutes those old IDs for current passage handles. Source ID,
version and source/chunk hashes allow the later comparison to bind current spans.
