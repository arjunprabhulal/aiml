# Save and load files with ADK artifacts

Install `requirements-lock.txt` in an isolated Python environment. Set `GOOGLE_API_KEY` privately before running the model-backed commands. Tests replay saved model turns offline.

## Run the example

```sh
python assistant.py "Review this ship.toml before I deploy to production."
```

The assistant uploads the supplied configuration, reads it with `load_artifacts`, and checks it against the bundled docuctl manual. Files remain in the local artifact store. Model-backed runs incur API usage.

```sh
python -m unittest -v test_assistant.py
```

`python record.py` runs the multi-step experiment, makes fresh model calls and replaces the saved results. It is an authoring command, not an offline replay.

## Recorded execution evidence

The recorder made real Gemini API calls and used the local tools and services in this lab. The [provider attempt metadata and output hashes](runs/docuctl-2026-10-25/provenance.json) identify the recorded output and captured attempts. Raw provider receipts remain private; the download excludes opaque model signatures and SQLite binaries. These records do not demonstrate browser interaction or reliability across other questions. Run the offline tests to exercise the selected replies without making paid model calls.
