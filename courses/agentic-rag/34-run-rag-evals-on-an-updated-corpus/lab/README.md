# Run RAG Evals on an Updated Corpus

Execute native SQLite FTS5 rankings on the same four published development
questions before and after an **explicitly synthetic** corpus change. No model,
vector replay, answer generation, installation, provider call or download runs.
The recorded environment is Python 3.12 with standard-library SQLite FTS5; there
are no third-party dependencies. Older-runtime compatibility was not tested.

From this directory:

```sh
python run.py --output runs/my-run/result.json
python -m unittest discover -v
python render_output.py --input runs/my-run/result.json --output /tmp/updated-evals.html
```

The driver writes actual rankings, metrics, stdout/stderr, test logs, source
hashes, command/interpreter and SQLite/runtime versions. The recorded run is in
`runs/2026-10-23-updated-evals/`. Python connect/connect_ex is refused during
ranking; this is not an OS-wide firewall or sandbox for arbitrary Python code.

## Frozen inputs and synthetic change

`fixtures/baseline-snapshot.json` and `development-cases.json` are byte-identical
copies from the published Module 6 comparison. No held-out questions are loaded.
The original versioning-lab files rebuild the exact baseline snapshot.

The update retains the original `path-write` summary verbatim as a prefix and
appends clearly labelled synthetic non-factual length padding in the same
paragraph. This changes bytes, content, length, revision and chunk identity
without inventing a Python API rule. Its fact-status metadata explicitly marks
the addition. The retained documentation URL supplies original provenance; it
does not imply an official page changed. The JSON summary is deleted. All other
source summaries remain unchanged.

`version_documents.py` and `load_documents.py` are exact published copies.
`lexical.py` contains verbatim extracted Module 6 lexical symbols and stdlib-only
dependencies. `evaluation_bindings.py` contains verbatim `bind_targets` and
`metrics` functions. Extraction source paths, line spans and hashes are in
`fixtures/provenance.json`; no unused vector SDK is imported. The provenance
file itself is pinned by the loader. Hashes establish local consistency, not
publisher authentication or factual correctness.

## Frozen retrieval and strict target binding

`run_rankings(snapshot, requests, config)` takes only case ID, original question
and API version; target labels never enter retrieval. The fixed Module 6 lexical
configuration keeps candidate budget three and cutoffs one and two. Every ASCII
alphanumeric question term is quoted and OR-joined for actual FTS5 BM25 search.
Requested version is filtered before top-k; chunk ID breaks native-score ties.
ASCII term extraction differs from SQLite's Unicode tokenizer. This is lexical
retrieval, not a semantic search claim. The lab bounds the corpus to 100 passages.

Targets bind logical source ID, API version, exact raw source hash and exact
chunk-text hash. Legacy target IDs are not current chunk IDs. Unchanged labels
fail on the updated snapshot with `target_binding_not_bijective`. Source logical
identity alone cannot rescue stale labels. Saved runs bind exact snapshot,
requests, fixed configuration and ranked payloads. Changed requests/config,
stale runs, duplicate candidates and inconsistent payload/hash bindings fail.
The validator also rederives the exact local native ranking and compares order,
scores and completeness; a consistently rehashed forged ranking is still refused.
This does not authenticate an adversary who can replace every reference.

## Explicit trusted local reannotation

`fixtures/reannotations.json` is trusted **local operator input**, separate from
retrieval. Each annotation names both snapshots, exact old/new target fields and
a reason. Both write questions retain their answer-bearing original summary, so
the fixture operator explicitly rebinds them to the changed whole paragraph.
The checker requires the exact old target, a unique new source/version/raw/text
match and the actual new current chunk ID. Receipts retain old/new identities
and hashes. No model grades semantic validity; no real approval or author identity
is asserted. Reannotation cannot silently change source ID or API version.

The deleted JSON target remains **not comparable**, with a
`deleted_target_source` reason and null metrics. It is never relabeled unsupported
or reassigned to another source. Without explicit annotations the changed write
targets also remain not comparable.

## Ranks and denominators

Recall@k divides target chunks retrieved within k by all labeled target chunks.
Reciprocal-rank@k is the inverse of the first target's rank within k, or zero on a
miss. Per-case output retains target ranks, target count and miss flags. The
unsupported backup question has no target: recall, reciprocal rank and miss are
null, and returned candidate count is kept. This is not an answer abstention test.

Paired means include only cases supported and bound in **both** snapshots. The
denominator excludes deleted/unresolved targets and the unsupported question;
those cases remain visible. Do not interpret a mean without that coverage. The
actual run retains unchanged ranks or regressions as observed. Synthetic changes
and already-used development cases support no general quality-gain estimate. No
threshold or retrieval parameter is tuned from the run.

Named checks cover `test_stale_targets_refused`, `test_changed_old_hash_refused`,
`test_changed_new_hash_refused`, `test_changed_new_chunk_id_refused`,
`test_deleted_target_not_silently_reassigned`,
`test_unsupported_metrics_null_and_denominator_excluded`,
`test_changed_request_cannot_be_compared`, `test_mutated_snapshot_refused`,
`test_labels_do_not_change_rankings` and `test_heldout_split_refused`.

Independent review prompted a saved-ranking revalidation guard. The authoring run
was rerun with unchanged queries/configuration; `rerun-history.json` retains the
prior actual result/execution hashes. The refreshed result has the same observed
rankings and metrics, not a new experiment or quality estimate.
