# Handle Ingestion Failures

Keep valid local documents while recording every rejected source. This lab uses
the same pinned original Python API summaries and loader as Load Developer
Documentation. Requires Python 3.11 or later, with no third-party dependencies,
network, models or credentials. Run from this directory:

```sh
python3 ingest.py --output runs/clean/result.json
python3 ingest.py --exercise-failures --output runs/failures/result.json
python3 -m unittest discover -v
```

The clean command exits 0 with four documents. The failure exercise deliberately
exits 2 with status `partial`, one accepted document and three failures:
`hash_mismatch`, `unreadable_source` and `invalid_utf8`. Exit 2 is expected; shell
automation must not treat a partial batch as complete. The exercise modifies
only temporary copies and removes them on exit. To isolate decoding failure it
updates the temporary manifest hash to match its deliberately invalid UTF-8 bytes.

Actual exercise output and 22 passing unit checks are in
`runs/2026-10-23-ingestion/`. `execution.json` records command, expected nonzero
exit status and source hashes. This is an executed local failure exercise, not
model inference or a live outage. Each record retains the original source URL,
version and fact status; the Python 3.13 API is documented only, not executed.

An invalid manifest aborts before processing. Individual source failures are
quarantined as structured records. An all-failed batch reports `failed`. The
program never silently repairs a hash mismatch or retries an unchanged invalid
file. Correct the source or explicitly review and update the pinned snapshot,
then rerun; the CLI does not resume or persist a retrieval index. The JSON output
is the reviewable batch artifact, not an automatic production publication.

Limits: 64 KiB per source; operator-controlled fixture directory; UTF-8 Markdown
only. Path validation rejects traversal and symlinks but does not defend against
concurrent file replacement. A matching hash proves byte identity, not factual
correctness or document freshness. Original summaries are reused exactly from
the baseline lab, with no new upstream verification claim.

Render an actual result for inspection with `python3 render_output.py --input runs/2026-10-23-ingestion/result.json --output /tmp/ingestion-report.html`. The HTML displays the saved run; rendering it does not execute ingestion again.
