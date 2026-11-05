# Compare agents and pipelines

This compares two frozen deterministic policies, not model agents or generated
answers. Both receive the same original question, API version and source
snapshot. Both start with the same broad `text` search and have identical maximum
step/search/read/source-byte budgets. The fixed pipeline searches once and reads
the first result. The scripted policy checks a configured literal marker after
reading and can use a question-only hand-coded rewrite for another search/read.
Its extra rules and additional actual tool effort are explicit confounds.
The result cannot isolate architecture from policy design or effort.

Only case ID, question and requested version enter execution. Labels join
**after** all policy runs. Legacy target IDs map to current passage IDs through
exact source ID, API version, raw-source SHA-256 and chunk-text SHA-256; binding
receipts keep both identities. The outcome checker also requires current source
metadata and actual read-text hashes to match. A known passage ID alone cannot
turn altered text into a pass.

The common outcome checks use `pass`, `fail` and `incomplete`, separately from
controller terminal states. Reading every exact bound target is a pass for this
source-retrieval check. A completed policy that misses its target fails; budget
exhaustion or a policy that stops incomplete remains incomplete. Controller/tool
errors fail supported cases. The unsupported question has no labeled retrieval
target and remains incomplete; its raw controller status and errors are still
retained. It is not counted as a correct abstention or an answer-quality pass.

All eight main trials remain in the result, including fixed-pipeline misses,
the scripted UTF-8-write miss and unsupported cases. Per-policy counts retain
all three outcome states. These four previously used development fixtures are
not a general quality estimate, winner selection, held-out evaluation or model
comparison. Tests verify equal inputs/budgets, label independence, exact legacy
bindings, failure/incomplete retention, altered-read refusal and trial joins.

## Runtime and frozen inputs

Python 3.11 or later, standard library only, with SQLite FTS5 available. No
installation, provider credentials, model, network request or download is used.
From this lesson directory:

```sh
python3 run.py --output /tmp/retrieval-result.json
python3 -m unittest -v
python3 render_output.py /tmp/retrieval-report.html
```

With `--output`, the runner writes full JSON and prints a concise summary. Without
it, stdout contains the full JSON. `tools.py`, `bm25.py`, `version_documents.py`,
`load_documents.py` and `refine.py` are copied unchanged from the preceding
search/read and refinement labs. The source snapshot and original four
**development** cases are copied exactly. No held-out question is loaded or
queried. Source-version metadata refers to the summarized Python API, not the
interpreter running the controller.

The frozen corpus is loaded before a run. Tool admission counters do not cover
fixture initialization, policy callback computation, process runtime, wall time,
model tokens or inference spend. A policy callback can block; this local runner
is not a hard timeout or process sandbox. Read bytes mean UTF-8 text bytes
reserved for authentic source handles, not total filesystem I/O or HTTP bytes.
The prepared corpus and tools enforce the size contract; a remote or streaming
tool with unknown output size would require a different admission mechanism.

The actual recording denies outbound socket connections. Full result JSON,
exact stdout/stderr, actual test output and source/environment hashes accompany
the run. The report renderer reads that record without calling tools. No timing
or new answer-generation measurement is claimed. Reproducing the same commands
under the same snapshot yields the deterministic result.

Actual result: `runs/2026-10-23-comparison/result.json`.
