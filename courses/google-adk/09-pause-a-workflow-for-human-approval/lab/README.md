# Pause a workflow for human approval

Use Python 3.12 or later. Keep the files together and run commands from `adk-human-approval-lesson/`.

## Set up

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

Export `GOOGLE_API_KEY` privately in this terminal. `.env.example` is an export
reference; the Python client does not load it. Then select the Gemini API:

```bash
unset GOOGLE_GENAI_USE_VERTEXAI DOCS_MODEL
export GOOGLE_GENAI_USE_ENTERPRISE=0
```

## Run the activity

```bash
python approval_client.py --reviewer learner --db learner-index.db
```

The client creates a new sample SQLite file and refuses an existing filename.
Read all SQL in the paused payload, then type exactly `approve` or `reject`.
Inspect `resumed_events` and `columns_after`. `--reviewer` is a local label,
not authentication. Ctrl+C or EOF before a decision leaves the migration unapplied.
The paused session lives in the same process and is lost when it closes.
Use a new database filename for another attempt; the SQL allowlist is not a sandbox.

Model-backed activity uses your provider account. The model configuration limits
each response to 1,024 output tokens.

## Check offline

```bash
python -m unittest -v test_migration_gate.py test_client.py
```

These checks exercise the actual code with saved replies or explicit fakes. They
make no provider requests. Saved replies illustrate the mechanism; use new cases
and inspect actual answers to evaluate a changed prompt.
