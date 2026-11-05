# Build Hybrid Retrieval

Fuse actual native SQLite FTS5 results with actual LangChain in-memory cosine
retrieval using preserved vectors. No embedding model runs in this lab. The
vector adapter, snapshot, recordings, four development cases and pinned dependency
files are copied unchanged from Add Vector Retrieval.

Requires Python 3.12 or later, SQLite with FTS5, and the exact dependencies in
`requirements.txt`/`requirements.lock`. Use the already prepared environment; no
package, model or network download is needed for the recorded run.

```sh
python3 run.py --output runs/my-run/result.json
python3 -m unittest discover -v
python3 render_output.py --input runs/my-run/result.json --output /tmp/hybrid-report.html
```

Run from this directory. `runs/2026-10-23-hybrid/` records real stdout, raw results,
tests, commands, environment and source hashes. This is saved-vector replay plus
fresh local SQLite, LangChain cosine and rank-fusion computations. Opening the
HTML report does not execute retrieval again. No held-out cases or fresh model
requests ran.

## Two branches receive the same question

`HybridRetriever(snapshot, embeddings).search(query, k=2, candidate_budget=3,
rank_constant=60, policy=None)` passes the exact original full question to the
saved-vector adapter. Unknown questions fail with `unrecorded_development_query`;
it never substitutes the lexical query for an unrecorded vector question.

The lexical branch extracts lowercased ASCII alphanumeric sequences. It accepts
at most 512 input characters, 32 extracted tokens and 64 characters per token,
rejecting blank or tokenless input. Duplicate tokens are removed in first-seen
order. Every token is quoted separately and joined by application-generated OR;
the complete MATCH expression is a bound SQL parameter. User words such as OR
are ordinary quoted terms, not interpreted query syntax.

These are application query rules; SQLite indexes passage text with its native
`unicode61` tokenizer. ASCII query extraction is not equivalent to unicode61:
non-ASCII text can be omitted or split, underscores split identifiers, no
stemming/synonyms/stopword removal occurs, and common words can match unrelated
passages. This small English fixture does not establish multilingual support.

Both branches apply the same version-equality policy before selecting candidates:
`{'version': {'$eq': '3.12'}}`. SQLite applies it in WHERE before ORDER/LIMIT;
LangChain uses the copied actual store's filter callable before the adapter's
stable score sort/truncation. A valid version with no eligible rows yields empty
lists. `candidate_budget` is per branch, not the final result count.

## Fuse ranks, preserve native scores

Each present branch contributes `1 / (rank_constant + rank)` with one-based rank.
Contributions are summed; a missing branch contributes zero. Native negative BM25
scores and cosine scores are retained for inspection but never added together.
The final order is descending fused score, then ascending chunk ID for exact ties.
Repeated chunk IDs across branches produce one row. Duplicate IDs within one
branch and inconsistent source/version/URL/text for a shared ID are rejected.

Output retains `lexical_score`, `vector_score`, both ranks, both contributions and
`fused_score`. Missing native scores/ranks are null. Top-k and candidate budget
must be non-Boolean integers in 1–100; budget must be at least k. The rank constant
must be a non-Boolean integer in 1–1,000,000. Invalid payloads and nonfinite native
scores fail before fusion. RRF ranks its supplied candidates; it cannot recover
passages absent from both candidate lists or establish that a question is answered.

See SQLite's [FTS query syntax](https://www.sqlite.org/fts5.html#full_text_query_syntax)
and the [RRF formula explanation](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking).
The latter documents the algorithm; this lab does not use an Azure service.

## Interpret the run honestly

The four cases are the same development-only questions from the preceding module.
The unsupported backup-policy question still retrieves candidates; retrieval is
not an answerability decision. No quality improvement, held-out accuracy, runtime
benchmark or production readiness is claimed. This CLI does not create a hosted
index, persistent service, automatic answer or new model recording. Original
source fact status and the documented-only Python 3.13 boundary remain unchanged.

The test suite includes controlled synthetic rank lists to isolate fusion guards;
those lists are not model or corpus execution proof.
