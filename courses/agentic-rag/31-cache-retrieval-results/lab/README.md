# Cache Retrieval Results

Cache completed **materialized retrieval results** from a real local FastAPI
endpoint. No model runs or answer generation occur. The local corpus is the exact
Module 10 snapshot of four original Python API summaries. The collections and
public Bearer identities are the same explicitly synthetic fixtures as the
collection-authorization lab; they are not real permissions or production auth.

The recorded run uses the prepared Python 3.12 environment, with exact installed
distributions in `requirements.lock`. No installation, download or provider API
call was performed. Older runtime compatibility was not tested. From this lab:

```sh
python run.py --output runs/my-run/result.json
python -m unittest discover -v
python render_output.py --input runs/my-run/result.json --output /tmp/cache-report.html
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

## Cache identity and lifetime

`POST /retrieve` accepts exactly `query`, `collection`, optional `version='3.12'`
and optional strict integer `k=2` (1–10). Query is a literal ASCII alphanumeric
term of 1–64 characters; case normalizes to lowercase. Version and collection
bounds match the authorization lab. Public fixture Bearer tokens are resolved
server-side. Identity and current collection grants are checked **before cache
lookup**. Clients cannot supply a principal, policy identity or bypass switch.

The canonical key includes the normalized request with resolved defaults,
principal, freshly derived authorization-policy hash, corpus snapshot identity,
and fixed pipeline name/version/max-passages configuration. Query case and
omitted defaults therefore share an entry; different principals, grants/policy,
versions, collections, k or corpus identity do not. The fixed pipeline performs
native SQLite FTS5 search, collection/version filtering before top-k, and exact
issued-handle reads. Global BM25 statistics are not tenant-isolated.

Only a nonempty `completed` result is stored. Empty retrieval is `incomplete` and
`bypass`; errors are HTTP 503 and never stored. Responses say `cache: miss`, `hit`
or `bypass`. Cached evidence contains exact source IDs, revisions, spans, hashes,
text and URLs, but **no executable read handles**, issued IDs or public read
endpoint. Registry expiry cannot invalidate this materialized projection.

`ResultCache` defaults to a 1-second monotonic TTL, four entries and 65,536 bytes.
It expires entries before lookup, promotes hits to most-recently-used, evicts the
least-recently-used entry as necessary, and refuses an entry larger than its byte
budget. Byte accounting is canonical serialized payload plus key bytes, not the
Python heap size. All bookkeeping is protected by one reentrant lock; puts and
gets deep-copy payloads. TTL is fixed from insertion rather than extended on hit.
The cache clears on shutdown; there is no persistence, distributed coherence,
single-flight suppression or cross-process sharing. Async endpoints perform the
short deterministic retrieval synchronously; this is not an event-loop capacity
or throughput design. SQLite connections stay on one thread per operation.

The body boundary refuses more than 8,192 bytes before parsing, including chunked
input, and handles duplicate keys, invalid UTF-8 and nonfinite JSON. Invalid
schemas yield 422; missing/unknown identity 401; denied collection 403; unsupported
media type 415. Error bodies do not expose private exception details. No auth,
CORS, TLS, service capacity or production safety claim follows from loopback use.

## Actual observations and failure checks

`run.py` starts actual Uvicorn subprocesses and sends actual HTTPX requests:
first miss, normalized hit, other-principal miss, refused identity/collection,
two incomplete bypasses, a real monotonic TTL expiry miss after a 1.05-second
wait, and two controlled tool failures. The failure factory is trusted test code,
not a public request field. No latency, cost saving or answer-quality claim is
made. Unit fake-clock behavior appears only in `test_fakeclock_expiry_and_lru`.

Named checks include `test_deepcopy_on_put_and_get`,
`test_authorization_before_cache_lookup`, `test_key_context_binding`,
`test_only_completed_cached`, `test_incomplete_and_failure_not_cached`,
`test_byte_bound_and_invalid_limits`, `test_parallel_bookkeeping` and
`test_real_http_hit_and_validation`. Actual run JSON, stdout/stderr, server logs,
test logs, commands, environment versions and source hashes are under
`runs/2026-10-23-cache/`. The HTML report renders saved execution data only.
