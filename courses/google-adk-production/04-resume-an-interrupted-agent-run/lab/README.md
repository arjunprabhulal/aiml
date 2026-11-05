# Resume an interrupted agent run

Run from this directory after installing `requirements-lock.txt` in your environment. Provider-backed commands require `GOOGLE_API_KEY` in the shell and incur model usage. The local environment must match the pinned dependencies; no install is performed by the example.

From the extracted lab directory, set `GOOGLE_API_KEY` in your shell. Choose new writable paths for the session database and tracker so this experiment leaves earlier runs intact:

```sh
export DOCS_DB=sqlite+aiosqlite:///resume-exercise.db
export DOCS_TRACKER=resume-exercise-tracker.json
python triage.py start 'The tokens page says deploy tokens never expire. File a docs issue.' --crash-after-write
```

The injected exit status is 137, after the local tracker write. Copy the printed `session` and `invocation` values. Keep both environment variables and the agent source unchanged, then replace the placeholders in the following command with those values:

```sh
python triage.py resume SESSION_ID INVOCATION_ID
```

Both commands can make fresh model requests. Inspect the tracker JSON: the retried call should reuse the stored function-call ID rather than append a second issue. This is the custom Python application's CLI, backed by a resumable `App` and `DatabaseSessionService`; it is not `adk run` or the Dev UI. A new prompt would start a new invocation instead of resuming this one.

## Offline checks and saved evidence

```sh
python -m unittest -v test_triage.py
```

These tests use controlled or recorded model responses; passing them is not a fresh model outcome. The saved model responses are from the docuctl experiment. `record.py` is a fresh experiment recorder, not an offline replay command; it may make provider calls and replace saved results. Do not run it to view existing evidence.

## Recorded execution evidence

The recorder made real Gemini API calls and used the local tools and services in this lab. The [provider attempt metadata and output hashes](runs/docuctl-2026-10-25/provenance.json) identify the recorded output and captured attempts. Raw provider receipts remain private; the download excludes opaque model signatures and SQLite binaries. These records do not demonstrate browser interaction or reliability across other questions. Run the offline tests to exercise the selected replies without making paid model calls.
