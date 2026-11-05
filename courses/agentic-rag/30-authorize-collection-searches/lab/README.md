# Authorize Collection Searches

Run real local FastAPI search/read requests against the pinned four-document
Python API summary corpus. The `serialization` and `files` collections, principals,
grants and public Bearer tokens are **synthetic teaching fixtures**, defined in
`fixtures/policy.json`. These tokens are not secrets, JWTs, real permissions or a
production authentication design. This lab generates no answer and calls no model.

The recorded run uses the prepared Python 3.12 environment. Exact installed
FastAPI, Starlette, Uvicorn, HTTPX and Pydantic distributions are pinned in
`requirements.lock`; no installation or download was performed. Older runtimes
were not tested. With that environment selected, from this directory:

```sh
python run.py --output runs/my-run/result.json
python -m unittest discover -v
python render_output.py --input runs/my-run/result.json --output /tmp/authorization-report.html
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

## HTTP contract

`GET /health` reports the loaded corpus and policy identities after application
startup. `POST /search` requires JSON with a literal ASCII alphanumeric `query`
(1–64 characters), `collection`, optional `version` (default `3.12`, numeric
major.minor, at most 16 characters), and strict integer `k` (1–10, default 2).
Extra fields, Boolean integers and raw FTS syntax are refused. Query case is
normalized. Collection names are bounded to 32 characters. Use the public fixture
header `Authorization: Bearer demo-reader` or `Bearer demo-editor`. The former can
search serialization; the latter can search both fixture collections.

Identity resolution and collection authorization happen before tool construction.
Search uses actual SQLite FTS5 native BM25 scores over the validated snapshot.
The inherited tool constructor refuses corpora above 100 passages. Search fetches
all possible native matches, filters collection and version eligibility, then
applies `k`, so an ineligible higher-ranked match cannot consume an eligible slot.
BM25 statistics remain global to this tiny corpus: this is content eligibility,
not tenant-isolated scoring or protection from statistical inference.

`POST /read` accepts exactly `{"handle": <one issued search result>}`. The server
keeps at most 64 authoritative issued handles for 60 monotonic seconds. Each
handle binds principal, collection, current policy identity, corpus snapshot,
search request, exact passage metadata and native rank. Reads require exact
issued-payload equality and recheck current identity/grants/policy/corpus before
returning the pinned source text. Unknown, expired, foreign, changed or stale
handles fail. Issued IDs are random opaque local receipt identifiers, not
cryptographic authorization credentials. Registry loss on restart invalidates
all handles; eviction can invalidate a handle before its TTL. Trusted policy
changes rederive the policy hash and invalidate previously issued handles.

HTTP statuses are 401 unknown/missing identity, 403 denied collection or invalid
read handle, 422 invalid JSON/schema, 413 body above 8,192 bytes, 415 unsupported
media type, and 503 a controlled tool failure. JSON duplicate keys, nonfinite
numbers and invalid UTF-8 fail safely. The application body bound does not bound
all server/socket memory. Errors expose stable codes, not paths or exception text.

## Execution and checks

`run.py` starts actual Uvicorn subprocesses on prebound loopback sockets and uses
HTTPX with environment proxies disabled. The recorded requests include successful
search/read, denied collection, unknown identity, foreign and tampered handles,
eligibility before top-k, invalid Boolean k, no matches, and a trusted failing
factory exposed only through `fixture_server.py`. No public fault switch exists.
The test suite also sends actual loopback HTTP requests; TestClient is used for
focused fixtures. SQLite connections are created, used and closed synchronously
inside the same async endpoint/event-loop thread; no cross-thread DB reuse occurs.
This single-process in-memory registry is not a shared session service, auth
system, CORS policy, capacity plan or production deployment.

Named regressions include `test_denial_before_tool_construction`,
`test_eligibility_before_k`, `test_foreign_handle_refused`,
`test_tampered_handle_refused`, `test_policy_revision_and_revoked_grant_refused`,
`test_corpus_over_100_rejected`, and
`test_real_http_body_and_authorization_boundary`. The fake-clock test is explicitly
named `test_fakeclock_expiry_and_capacity`; demo HTTP observations use real clocks.
The source summaries and snapshot are exact copies of Module 10, with original
source URLs, revisions and spans retained. They are original summaries, not copied
vendor documentation. No framework SDK or production authorization is simulated.

`runs/2026-10-23-authorization/` retains actual JSON, stdout/stderr, server logs,
test output, commands, runtime/package versions, result hash and source hashes.
The saved report renders these observations without performing new requests.
