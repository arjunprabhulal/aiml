# Load procedures with SkillToolset

The docs assistant loads skills from `skills/`. The release-notes procedure fetches bundled pull-request fixtures, reads its style guide and runs `scripts/group_changes.py` through the configured local executor.

Use Python 3.12 or later. From this extracted lab directory:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
```

Set `GOOGLE_API_KEY` in your terminal. Read `agent.py`, `skills/release-notes/SKILL.md` and the skill's script before running:

```sh
python agent.py "Write the release notes for docuctl 2.4.0."
python agent.py "Write the release notes for docuctl 9.9.0."
```

Each agent command invokes the model. The known version should follow the skill and call the script; the unknown version should report the fixture tool's error. A similar-looking answer without `run_skill_script` does not verify script execution. The local executor runs reviewed scripts with your process's permissions and inherited environment; it is not an isolation boundary.

For an already installed local model, set `DOCS_MODEL=ollama_chat/gemma4:e2b`. These commands do not install a model.

## Offline tests

```sh
python -m unittest -v test_agent.py
```

The tests replay saved model responses through real skill loading, skill tools and the script executor. They make no new model requests. `record.py` is a separate live-recording utility and overwrites its result files.

## Recorded execution evidence

The recorder made real Gemini API calls and used the local tools and services in this lab. The [provider attempt metadata and output hashes](runs/docuctl-2026-10-25/provenance.json) identify the recorded output and captured attempts. Raw provider receipts remain private; the download excludes opaque model signatures and SQLite binaries. These records do not demonstrate browser interaction or reliability across other questions. Run the offline tests to exercise the selected replies without making paid model calls.
