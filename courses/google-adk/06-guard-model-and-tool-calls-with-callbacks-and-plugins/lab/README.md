# Guard model and tool calls with callbacks and plugins

A developer asks the assistant to check `docuctl.toml`, but the file contains a credential identifier. Another request asks it to read a path outside the project. We need code that removes the matching identifier before storage or model use, and code that refuses an out-of-workspace read before the tool runs.

Use Python 3.12 or later. All commands run from `adk-callbacks-plugins-lesson`.

## Prepare the callback and plugin project

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit the private root `.env` and replace its placeholder with your Gemini API key. The entrypoint loads it before constructing the agent; exported shell settings take precedence. Keep `.env` out of version control. Chat commands use your provider account.

## Check configuration through the guarded Python Runner

```bash
python guarded.py "Read docuctl.toml and compare it with docs/config.md. What should change?"
```

## Exercise the workspace refusal

```bash
python guarded.py "Read ../workspace-old/docuctl.toml and compare it with docuctl.toml."
```

## Run redaction, storage and path-boundary checks

```bash
python -m unittest -v test_guarded.py
```

## What to inspect

The Python Runner receives the full App with RedactSecrets, not a bare agent. Only use the supplied AWS example identifier AKIAIOSFODNN7EXAMPLE. The plugin redacts incoming text before storage and file-tool results before model use; the path callback refuses a path outside workspace. This is one identifier format and one tool rule, not a complete secret scanner or OS sandbox.

## Offline data

The bundled JSON contains saved model turns for replay tests and small teaching examples. These are saved-response replays, not new inference. Test commands replace the model while exercising the actual SDK mechanisms. Model wording in your own conversations can differ.
