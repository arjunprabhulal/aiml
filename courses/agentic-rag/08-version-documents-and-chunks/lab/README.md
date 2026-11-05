# Version Documents and Chunks

Build a deterministic local corpus snapshot from the same four original Python
API summaries used in the preceding ingestion module. Requires Python 3.12 or
later, with only the standard library. No network, install, model or credentials.

From this directory:

```sh
python3 version_documents.py --output runs/my-run/snapshot.json
python3 demo.py --output runs/my-demo
python3 -m unittest discover -v
python3 render_output.py --input runs/my-demo/result.json --output /tmp/version-report.html
```

The recorded local demo is in `runs/2026-10-23-versioning/`, including the initial,
text-change and metadata-change snapshot JSON, comparisons, stdout, tests and
execution/source hashes. These are actual local file operations, not inference.
Opening the saved report does not execute ingestion again.

## Identities have different jobs

- `source_id` identifies one logical document. `version` identifies the documented
  Python API version; it is not an ingestion revision.
- `sha256` hashes the exact UTF-8 file bytes before newline normalization.
- `metadata_sha256` hashes canonical JSON of path, title, API version, URL and fact
  status. A metadata-only change therefore cannot silently reuse the old revision.
- `document_revision` hashes source ID, byte hash and metadata hash.
- `chunk_id` hashes document revision, the complete chunker configuration, exact
  normalized paragraph text hash and its 1-based inclusive line span.
- `snapshot_id` hashes the schema version, chunker configuration and complete sorted
  document records, including normalized text, metadata and every chunk. Manifest ordering does not affect it.

Canonical JSON uses sorted object keys, compact separators and UTF-8. Paragraph
chunks are exact slices of normalized text, preserving internal and final line
endings. Blank separator lines are excluded. CRLF becomes LF after verifying the
original byte hash. No embeddings or retrieval algorithm are introduced here.

Chunker name, version, newline policy and separator are explicit. Unknown configs
are rejected rather than pretending the code implemented a different algorithm.
Changing that implementation requires a new supported config and fresh snapshots.
The current policy invalidates every chunk of a changed document. It deliberately
trades reuse for a simple rule preventing mixed document revisions.

## Read the deliberate revisions

`fixtures/initial/` preserves the module3 original summary bytes and source
metadata. `fixtures/text-change/` adds a clearly marked local teaching paragraph
to `path-write` and changes its fact status to describe that local revision;
both raw bytes and metadata change. It is not an upstream Python documentation
update. `fixtures/metadata-change/` changes only that source's title; its raw byte
hash stays the same, while its document revision, chunk IDs and snapshot change.
The logical source ID and API version remain the same in both cases.

The changed manifest pins the deliberately changed bytes. Editing bytes without
updating their reviewed hash fails with `hash_mismatch`; this program never
silently repins them. The initial summaries retain existing fact status, including
the Python 3.13 summary's documented-only limit. No upstream claims were rechecked
and no documented Python 3.13 API was executed.

## Limits

The copied module3 loader rejects traversal, symlinks, nonregular files and files
over 64 KiB. Fixtures must be operator controlled; checks do not prevent a
concurrent local process replacing files between validation and opening. Hashes
identify bytes and policy; they do not prove correctness, freshness, authenticity
or permission. JSON output is a local artifact, not a deployed retrieval index.
There is no deletion, resume or production publication operation in this lab.

## Validate saved snapshots before consuming them

`validate_snapshot(snapshot)` raises `IngestionError('invalid_snapshot')` for
unsupported configurations, malformed documents, duplicate identities, inconsistent
metadata/revisions/chunks or a mismatched snapshot ID. It rederives exact paragraph
spans, chunk text and hashes rather than trusting stored chunk IDs. Consumers must
call it before writing a checkpoint or replacing an index. Same-ID changes to
saved normalized text, metadata, chunks or config are rejected.

This checks internal consistency, not authenticity. The loader verified original
bytes when it created the snapshot; saved normalized text cannot reconstruct
whether its original file used CRLF. An actor replacing an artifact and every
reference to its identity can create another consistent artifact. These hashes
are not signatures or a substitute for trusted storage.
