# Call the docs assistant over A2A

`server.py` exposes the docs agent using `to_a2a`. `client.py` gives a release coordinator a `RemoteA2aAgent` that discovers the card and streams the remote task. Read both files before starting them.

Use Python 3.12 or later. From this extracted lab directory:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
```

Set `GOOGLE_API_KEY` in each terminal that runs an agent. The two agent loops can both invoke the model.

## Terminal 1: server

```sh
python server.py
```

Keep this process running. It serves the local example on port 8001 with in-memory task and session stores. It has no authentication.

## Terminal 2: client

Open another terminal in this directory:

```sh
source .venv/bin/activate
curl -s http://localhost:8001/.well-known/agent-card.json
python client.py "How do I roll back production to r41?"
```

The card advertises the RPC address; it does not make uvicorn listen there. Check error fields on returned events, including an unavailable server or a card whose RPC URL has another origin. When supplying your own HTTPX client, configure its timeout on that client.

Stop the server with Ctrl-C when finished. For an already installed local model, set `DOCS_MODEL=ollama_chat/gemma4:e2b` in the relevant process's terminal; no model is downloaded by this lab.

## Local integration tests

```sh
python -m unittest -v test_a2a.py
```

The tests start a loopback server on a free port and replay saved model responses on both sides. The A2A card, transport and task stream are real; there are no new model requests. `record.py` performs separate live recordings.

## Recorded execution evidence

The recorder made real Gemini API calls and used the local tools and services in this lab. The [provider attempt metadata and output hashes](runs/docuctl-2026-10-25/provenance.json) identify the recorded output and captured attempts. Raw provider receipts remain private; the download excludes opaque model signatures and SQLite binaries. These records do not demonstrate browser interaction or reliability across other questions. Run the offline tests to exercise the selected replies without making paid model calls.
