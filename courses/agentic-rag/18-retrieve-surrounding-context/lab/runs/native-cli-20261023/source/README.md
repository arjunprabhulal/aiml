# Retrieve Surrounding Context

Expand explicit seed chunk IDs into bounded context windows using the same
original synthetic Aster developer documents as Choose Chunk Boundaries. This
lab performs actual local source processing and expansion, not search, model
inference or an answer-quality evaluation. Neighbor passages are not retrieval
hits. The seeds are controlled fixture inputs, not model-generated evidence.

Requires Python 3.12 or later; standard library only. From this directory:

```sh
python3 run.py --output runs/my-run/result.json
python3 -m unittest discover -v
python3 render_output.py --input runs/my-run/result.json --output /tmp/surround-report.html
```

The actual run and its stdout, tests, environment and source hashes are under
`runs/2026-10-23-surround/`. The HTML report displays those saved data; opening it
does not rerun expansion. No network, model, embeddings or downloads are used.

## Validate before adding neighbors

`build_index(manifest, CONFIGS['paragraph'])` preserves raw source hash, normalized
text hash, revision, source/API version, section, order and exact spans. The
copied `chunk_index.py` is byte-identical to Choose Chunk Boundaries. It supports
plain prose with ATX headings and blank-line paragraphs, not a full Markdown
parser. CRLF is normalized to LF after checking the original bytes. Offsets are
zero-based half-open Python character positions into normalized text; line spans
are one-based inclusive. These are not byte offsets or model-token counts.

`expand_context(index, seed_ids, radius=1)` first validates the complete index by
rederiving its chunks and canonical identity. Seeds must be unique current IDs
from that index. Unknown/stale IDs fail rather than being silently rebuilt or
matched by text. The authoritative seed payload comes from the validated index;
external seed text is never trusted. Radius must be a non-Boolean integer from
0 through 3. An empty seed list returns no groups.

For each seed, choose at most `radius` preceding/following chunks inside exactly
the same source, API version, document revision and section. Overlapping windows
merge and deduplicate their members. Separate nonoverlapping windows remain
separate. Text stays in source order; groups order by the earliest seed rank,
then stable source/order/ID ties. Each member is explicitly a `seed` or `neighbor`;
only seeds retain their original one-based retrieval rank. Adding a neighbor
does not invent a retrieval score or a new hit.

The recorded two seed IDs point to the first and third paragraphs of Create a
copy. Radius one produces a single three-chunk window with roles
`seed, neighbor, seed`, retaining both seed ranks. The middle neighbor contains
the existing-path qualifier. The window never absorbs List documents, another
source, or the version-two API contract.

## Downstream handoff

Each group includes its exact source slice, section/revision, start/end orders,
chunk IDs, seed IDs, seed ranks and member roles. `validate_windows(index, result)`
recomputes the complete result, refusing changed payloads, spans or provenance.
Consumers should validate before converting each group into an atomic prompt
context block. This lab imposes a chunk-radius bound, not a model-token budget.
The next budget lesson handles the latter.

Named guards include `test_unknown_and_stale_seeds_refused`,
`test_invalid_radius_refused`, `test_duplicate_and_malformed_seeds_refused`,
`test_malformed_index_order_span_payload_refused_before_expansion`,
`test_tampered_windows_seed_provenance_refused`, and
`test_no_cross_document_version_or_section`.

Hashes validate consistency, not authenticity or truth. Saved normalized text
cannot reconstruct original CRLF bytes; original byte hashes were checked while
loading. An actor replacing an artifact and every identity reference can make a
new internally consistent artifact. Fixture files must be operator controlled;
path checks do not prevent concurrent file replacement. The API descriptions
are explicitly synthetic teaching contracts, not upstream facts or an incident.
