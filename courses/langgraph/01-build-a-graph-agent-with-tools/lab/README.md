# Tool-calling graph

ToolNode executes the supplied local review-queue tools. A reply without tool calls ends the graph. Expected domain errors become tool messages; unrelated errors stop execution.

## Setup

Run from a working copy of this lesson folder:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
```

Live execution uses `GOOGLE_API_KEY` and defaults to Gemini `gemini-3.8-flash`. Scripts do not load `.env` automatically. Fresh provider requests can incur charges. The optional Ollama path uses an existing service and already installed model selected with `REVIEW_MODEL`; compatible APIs do not imply equal answers.

## Execute

```bash
python graph.py "Which open pull request has failing CI, and why?"
```

This command makes fresh model requests. `record.py` runs the supplied scenarios and overwrites `runs.json`; use a disposable copy when recording. Existing `runs.json` and `run-output.txt` preserve historical supplied model observations. They do not measure a new run. The tools and conversation inputs are local fixtures, not an external review service.

## Check without a model

```bash
python -m pytest -q test_graph.py test_live_probe.py
```

Tests execute the actual SDK graph with scripted model replies and inspect supplied recordings. They require no model server or API key and do not prove fresh model inference. Run tests from this folder to avoid importing another lesson's `graph.py`.

The older flat-message recording is preserved unchanged in `runs/legacy-original-2c163e936291/runs.json`. The root `runs.json` uses the recorder’s grouped tools-step format and is the fixture for the current tests. These are different historical observations, not two runs of the current repair.

## Genuine model observation, October 23, 2026

The saved [run manifest](runs/20261023-genuine-gemini/manifest.json), [actual process stdout](runs/20261023-genuine-gemini/stdout.txt) and [structured events](runs/20261023-genuine-gemini/events.json) record one bounded Gemini `gemini-3.8-flash` run. It made two generation requests and two token-count requests. The graph followed `agent → tools → agent`: the model requested `get_diff(415)` and `get_ci_status(415)` in one reply, then explained that `DEFAULT_TIMEOUT` changed from 10 to 30 while `test_default_timeout` expected 10.

The provider reported 591 input tokens and 106 candidate tokens, 697 total. It supplied no separate thinking-token count. Usage is not a billing receipt. This task uses the supplied local PR fixture; it does not inspect a live code host or run CI.

[Desktop](runs/20261023-genuine-gemini/images/completed-end-1440@2x.png), [390px](runs/20261023-genuine-gemini/images/completed-end-390@2x.png) and [320px](runs/20261023-genuine-gemini/images/completed-end-320@2x.png) images are original views of the same completed Python PTY process. They show completed scrollback, not three runs. The [outcome review](runs/20261023-genuine-gemini/outcome-review.json) checked the answer against the tool results, request accounting, call IDs and original media.

`live_probe.py` is the exact probe source used for this observation. It requires an external in-process approval guard before constructing the SDK client or reading credentials. That private operator enforces the recorded HTTP and token limits and is not bundled here. Running `python live_probe.py` directly refuses without spending. Do not bypass its handshake. The normal `graph.py` command above remains available for separately authorized experiments; it does not enforce the external operator's spending policy.

The 18 probe tests use fixed replies to check refusals, tool scope, call limits and completion handling. Together with the 10 graph tests, the command above runs 28 offline tests. These scripted tests and the genuine run are separate evidence. Historical `runs.json` and its tests remain unchanged.
