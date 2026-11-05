# Persist session state and long-term memory

A developer tells the assistant which docuctl version they use, then returns in a new conversation. The version should still be available. Asking “Which release did you mention earlier?” needs something different: a search over past conversations. We will implement both and check what survives a process restart.

Use Python 3.12 or later. All commands run from `adk-sessions-memory-lesson`.

## Prepare the session and memory project

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit the private root `.env` and replace its placeholder with your Gemini API key. The entrypoint loads it before constructing the agent; exported shell settings take precedence. Keep `.env` out of version control. Chat commands use your provider account.

## Save a preference in Dana's user state

```bash
python session_client.py "I am on docuctl 1.x. How do I roll back production to r41?" --user dana
```

## Read the same user's state after restarting the client

```bash
python session_client.py "Which docuctl version am I using?" --user dana
```

## Make the first conversation searchable before the follow-up

```bash
python session_client.py "I am on docuctl 1.x. How do I roll back production to r41?" --user dana --remember --followup "Which release did you tell me to revert production to earlier?"
```

## Run the SQLite and memory checks

```bash
python -m unittest -v test_assistant.py output_cap_check.py
```

## What to inspect

The client prints session_id, transcript and state as JSON. Keep the same --user and SQLite file for the restart comparison. Add --session YOUR_SESSION_ID to resume a conversation; omit it for a new one. --remember with --followup adds the first finished session to process-local memory. Exiting loses memory, while SQLite state survives. --user is a local test identity, not authentication. The client closes the runner and database service.

## Offline data

The bundled JSON contains saved model turns for replay tests and small teaching examples. These are saved-response replays, not new inference. Test commands replace the model while exercising the actual SDK mechanisms. Model wording in your own conversations can differ.

## Recorded execution evidence

The recorder made real Gemini API calls and used the local tools and services in this lab. The [provider attempt metadata and output hashes](runs/docuctl-2026-10-25/provenance.json) identify the recorded output and captured attempts. Raw provider receipts remain private; the download excludes opaque model signatures and SQLite binaries. These records do not demonstrate browser interaction or reliability across other questions. Run the offline tests to exercise the selected replies without making paid model calls.
