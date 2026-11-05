# Track passage sources

Build a passage record that can be checked against its local source file. A passage
stores its source path, the SHA-256 of the entire file, a 1-based inclusive line
span, exact text, and supplied source ID, API version and documentation URL. The
chunk ID hashes these identifying fields. Source metadata changes produce a new
ID. Line endings remain part of the passage text and file hash.

## Run

Requires Python 3.11 or later. Dependencies: Python standard library only. No
installation, model, network request, credentials or downloaded data is needed.
Run from this lesson directory:

```sh
python3 sources.py
python3 -m unittest -v test_sources.py
```

The first command prints JSON. The actual recorded run is
`runs/2026-10-23-ingestion/run.json`. It contains the bound `path-write` passage,
the verified text and the rejection returned after changing the stored text.
Compare a fresh run without changing the recording:

```sh
python3 sources.py > /tmp/track-passage-sources-run.json
diff runs/2026-10-23-ingestion/run.json /tmp/track-passage-sources-run.json
```

An empty diff means this deterministic source-verification run reproduced the
record. It does not test a model or answer quality.

## Inputs and outputs

`fixtures/sources.json` preserves the supplied original Python API summaries from
the earlier evaluation dataset lesson. The files in `fixtures/docs/` contain those
summaries exactly, matching the document-loading lesson. These are local summary
fixtures, not fetched copies of the Python documentation. The version and URL
fields describe the summarized API; they do not select the interpreter running
this lab. The Python 3.13 summary remains documentation-only input.

`bind_passage(root, source_path, start_line, end_line, ...)` returns an immutable
`Passage`. `verify_passage(root, passage)` reconstructs the passage from current
file bytes and rejects any mismatch. It returns the exact source excerpt after a
successful comparison. It does not silently update stale records.

## Failure checks

The tests exercise real temporary files: changed source bytes; altered passage
text, hash, ID and span; out-of-bounds or non-integer spans; blank passages;
non-normalized, absolute, missing and parent-traversal paths; symlink escape; and
invalid UTF-8. Files must be regular files and at most `MAX_BYTES` (1,048,576
bytes). The reader requests at most `MAX_BYTES + 1` bytes, including when a file
grows after it is opened. Tests cover rejection above the limit, acceptance at
the exact limit, and rejection of directories and named pipes before reading. A CRLF test checks that line endings survive reconstruction.

Any edit anywhere in a file invalidates all its previous passages because each
record pins the whole source snapshot. This conservative behavior is deliberate.
A new snapshot requires newly bound passages. Rebinding after an edit does not
establish that a downstream index has removed stale records.

Hashes detect mismatches. They do not authenticate the author, establish access
permission, or prove that a summary is accurate. Supplied metadata is carried
through, not independently verified. The path check assumes trusted local files
that remain unchanged between the path check and read; this is not a secure
sandbox for concurrently hostile filesystem changes. This lab does not parse
PDFs, perform retrieval, or generate answers.
