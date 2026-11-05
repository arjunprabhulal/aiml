# Rerank retrieved passages

This lab runs a transparent deterministic token-coverage heuristic as a second
stage over actual hybrid candidates. It is not a learned reranker, cross-encoder
or model. It compares query/passage token sets without labels or expected answers.

The tokenizer is the hybrid retriever's `question_terms`: lowercase ASCII
alphanumeric runs, at most 512 input characters, 32 token occurrences and 64
characters per token. It preserves first occurrence while removing duplicates.
No stopword removal, synonym expansion or linguistic understanding is used.
For each candidate, the score is the number of distinct query tokens present in
the passage divided by the distinct query-token count. Exact coverage ties keep
the incoming RRF rank. The trace keeps query tokens, matched tokens, counts,
original branch ranks/native scores, fused score and incoming/reranked positions.

`rerank` validates the snapshot and each candidate's exact source ID, chunk ID,
API version, URL and text. It rejects unknown/duplicate candidates, altered
payloads, invalid ranks and nonfinite/invalid upstream scores. It cannot invent
a new chunk. The requested top-k truncates only after all candidate features
are calculated. Empty candidates return an empty list after input validation.

The actual four development runs retain every incoming order. For the UTF-8
write question, the read and write summaries tie on overlap and the read passage
stays first. The unsupported backup question still receives candidates. A
separate unfiltered diagnostic reuses the same first development question and
shows read/write overlap across all supplied versions. No label or new query is
introduced by this diagnostic. A separate controlled candidate-order contract
check reverses the actual replacement-question candidate list and records how
coverage reorders it. That check is not an evaluation case or a quality gain. These results show the heuristic's limits, not a
retrieval improvement. Tests verify identity preservation, token receipts,
label independence, incoming-order ties, empty inputs, malformed requests,
unknown vectors and changed candidate payloads.

## Runtime and frozen inputs

Requires Python 3.12 or later because the pinned NumPy version requires it.
`requirements.txt` pins the direct installed dependencies and `requirements.lock`
records their installed dependency closure. No installation was performed.
Use an environment with these packages already present, then run from this
lesson directory:

```sh
python run.py
python -m unittest -v
python render_output.py /tmp/module6-report.html
```

The hybrid, vector, document-loading and versioning cores are copied unchanged
from the preceding labs. SQLite FTS5 executes a quoted OR expression over the
original question's lowercase ASCII alphanumeric terms; the vector store replays
the exact same full question's saved embedding. No prompt prefix or embedding
computation is added. Both branches apply the requested version before selecting
candidate passages. RRF uses one-based ranks, not native score arithmetic.

`fixtures/vectors.json` is byte-identical to the earlier Qwen embedding recording.
Its provenance file retains the original run, model digest, query instruction
and file hash. The raw historical recording includes held-out vectors; only the
four original development questions are exposed and queried here. Source text,
version and current chunk identities come from the frozen versioning snapshot.
The copied validator checks normalized snapshot integrity. Raw source identity
and author authenticity remain provenance assumptions; hashes alone do not
establish authorization or factual accuracy.

The actual local execution appears in `runs/2026-10-23-rerank/result.json`, with
exact `stdout.txt`, `stderr.txt`, actual `tests.txt` and source/runtime hashes in
`execution.json`. Outbound socket connections were denied during the recorded
run. This is actual framework retrieval over preserved vectors, not a new model
run. The HTML renderer reads the record without running retrieval.
