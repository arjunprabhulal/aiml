# Scaffold, lint, and run an ADK project with Google Agents CLI

This is the complete `agents-cli-create-run` teaching lab. Extract it and begin in this directory. Install Python 3.12+ and uv before running the commands below.

## Model authentication

Before sending a question, edit the generated project’s `.env`: comment out its Vertex AI GOOGLE_* settings and set GEMINI_API_KEY to your own AI Studio key. Keep `.env` private. The model and credentials used by a coding assistant are separate from those used by the agent. The default model is gemini-3.8-flash; set DOCS_MODEL to an appropriate Gemini model ID when needed.

## Commands, in lesson order

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
LAB_DIR="$PWD"
```

```bash
LAB_DIR="$PWD"
agents-cli scaffold create docuctl-docs --agent adk --region us-central1 --prototype --agent-guidance-filename AGENTS.md -y
cp -R "$LAB_DIR/docuctl_docs/." docuctl-docs/app/
cd docuctl-docs
agents-cli install
agents-cli info
```

```bash
export DOCS_MODEL=gemini-3.8-flash
```

```bash
# Turn 1: start the local server on port 18080 and ask about production rollback
agents-cli run "I use docuctl 2.x. How do I roll production back to r41?" --start-server

# Inspect the live A2A Agent Card while the local server is running
curl -s http://127.0.0.1:18080/a2a/app/.well-known/agent-card.json | python3 -m json.tool

# Turn 2: paste the session ID printed above
export SESSION_ID="PASTE_THE_SESSION_ID_FROM_TURN_1"
agents-cli run "And on staging?" --session-id "$SESSION_ID"

# Stop the background server when finished
agents-cli run --stop-server
```

```bash
cd "$LAB_DIR"
"$LAB_DIR/.venv/bin/python" -m unittest -v test_create_run.py
```

## What the checks establish

Offline tests exercise local helpers and supplied examples. They do not invoke Gemini, deploy infrastructure, register an agent or verify telemetry delivery. Model-generation commands can incur charges; deployment and registration require your own cloud resources and credentials.

The saved session contains two actual CLI turns against the hosted model and the live local Agent Card. Provider signatures are omitted; private raw-log hashes are retained in the record.
