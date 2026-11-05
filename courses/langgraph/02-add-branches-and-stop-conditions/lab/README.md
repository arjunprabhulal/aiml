# Branches and stop conditions

Repeated tool names and exact arguments stop before execution. Argument key order does not matter. A separate step limit bounds calls with different arguments. A named stop is not a completed answer.

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
python graph.py "Keep checking CI on #415 until it is green."
```

This command makes fresh model requests. `record.py` runs the supplied scenarios and overwrites `runs.json`; use a disposable copy when recording. Existing `runs.json` and `run-output.txt` preserve historical supplied model observations. They do not measure a new run. The tools and conversation inputs are local fixtures, not an external review service.

## Check without a model

```bash
python -m pytest -q test_graph.py test_live_probe.py
```

Tests execute the actual SDK graph with scripted model replies and inspect supplied recordings. They require no model server or API key and do not prove fresh model inference. Run tests from this folder to avoid importing another lesson's `graph.py`.

## Genuine step-limit observation, October 23, 2026

The [run manifest](runs/20261023-genuine-gemini/manifest.json), [actual process stdout](runs/20261023-genuine-gemini/stdout.txt) and [structured events](runs/20261023-genuine-gemini/events.json) preserve one bounded Gemini `gemini-3.8-flash` run. The model proposed `get_diff(415)` and `get_ci_status(415)` in one reply. With `recursion_limit=3`, the real graph took `agent → stop` and returned `step_limit` before either tool executed. The final text, `I stopped before answering (step_limit).`, comes from graph code, not the model. This run does not show a correct answer or an observed CI result.

Exactly one generation request and one token-count request ran, without retries. The provider reported 243 input tokens and 34 candidate tokens, 277 total; it supplied no separate thinking-token count. Usage is not an invoice. These proposals concern the supplied local PR fixture, not a live code host.

[Desktop](runs/20261023-genuine-gemini/images/completed-end-1440@2x.png), [390px](runs/20261023-genuine-gemini/images/completed-end-390@2x.png) and [320px](runs/20261023-genuine-gemini/images/completed-end-320@2x.png) originals show completed scrollback from the same Python PTY process. The [independent outcome review](runs/20261023-genuine-gemini/outcome-review.json) checked the raw model proposal, native trajectory, hashes, request accounting and original media.

`live_probe.py` is the exact source used for this run. It requires an external in-process approval guard before constructing a client or reading credentials. The private operator enforces the recorded HTTP and token limits and is not bundled. Running `python live_probe.py` directly refuses without spending; do not bypass the handshake. The normal `graph.py` command remains available for separately authorized experiments and does not implement the private operator's spending policy.

The offline command above runs 15 graph tests and 12 probe tests, 27 total. Probe tests use fixed replies to check refusals, call and tool limits, and honest completion labels when the target branch is not observed. Historical `runs.json` and its tests remain unchanged. This observation covers the step-limit branch; it supplies no fresh model evidence for the repeated-call branch.
