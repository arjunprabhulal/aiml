# Build your first ADK agent with Gemini

A small documentation assistant explains commands from `docs_assistant/docuctl.md`.
docuctl is fictional: this lab does not install or execute a deployment CLI.

## Setup

Use Python 3.12 or later. From this `adk-first-agent` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp docs_assistant/.env.example docs_assistant/.env
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and copy with
`Copy-Item docs_assistant/.env.example docs_assistant/.env`.
Edit `docs_assistant/.env` and replace `replace-with-your-key` with your Gemini API
key. Keep that file private. The example selects the Gemini API; previously
exported backend/model variables take precedence over `.env`.

## Terminal chat

```bash
adk run --in_memory docs_assistant
```

Ask: `How do I deploy to staging and list its releases?`
Compare the answer with the two staging commands in the guide. Then ask:
`How do I configure automatic database backups?` The guide has no backup policy,
so the assistant should say that it does not cover it. Wording can vary.
`example-conversation.txt` illustrates the expected behavior; it is not a saved
model response. Type `exit` to stop. Conversations call Gemini and use your provider account.

## Development Web UI

From this same directory:

```bash
adk web --host 127.0.0.1 --port 8000 .
```

Open http://127.0.0.1:8000, select **docs_assistant**, and ask the same question.
This is a separate conversation using the same agent definition. Inspect the
Events view if you want to see ADK's events. Press Ctrl+C to stop the server.
ADK Web is a local development interface.

## How the example works

`__init__.py` exposes `agent.py`, which exports `root_agent` for ADK to load.
Python reads `docuctl.md` when the module loads. Its entire text becomes part of
the agent's instruction. ADK runs the conversation with Gemini. No tools are
configured, so the agent cannot deploy services or look up additional files.
Restart chat after editing the guide or instruction.

An instruction guides generation; check suggested commands against the guide.
This example does not enforce factual correctness or protect real deployments.

## Offline checks

```bash
python -m unittest -v test_agent.py
```

The checks load the real ADK agent, check its guide and settings, and exercise
missing-guide and invalid-name failures. They make no model requests and do not
measure generated-answer quality. `sample-questions.json` contains practice inputs
and the commands to compare with the guide; it is not a saved conversation.

## Next lesson

Use a Python Runner when your own application must create sessions and handle
events. The event-stream lesson develops that application code.

To record fresh responses from the Python Runner, export your Gemini API key privately and run `python record.py`. This updates `recorded-conversation.json` and `example-conversation.txt`; it makes two hosted-model requests.
