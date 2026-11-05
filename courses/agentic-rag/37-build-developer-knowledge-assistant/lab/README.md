# Developer Knowledge Assistant

A local question-answering application for fictional **docuctl** documentation.
It combines the Agentic RAG course's retrieval, application and runtime controls
in a browser UI and CLI. It never executes the commands found in documentation.

## Start the application

Requires Python 3.12 or later. Extract the complete lab ZIP, then open this folder.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m uvicorn api:app --host 127.0.0.1 --port 8120
```

Open http://127.0.0.1:8120. The default provider is **extractive**: answers quote
the retrieved passages verbatim. It needs no model, API key or network service.

In another terminal, from the same folder:

```sh
source .venv/bin/activate
python cli.py "How do I roll back a staging deployment?"
python cli.py "How do I deploy staging?" --version 3.4
python cli.py "Who won Wimbledon?"
```

The bundled access tokens are `reader-demo-token` (handbook only) and
`maintainer-demo-token` (handbook and operations). They demonstrate server-side
grants, not an identity provider. Change `DOCS_READER_TOKEN` and
`DOCS_MAINTAINER_TOKEN` before using your own documents; keep this teaching server
on loopback. There is no account system or public deployment configuration.

## Use Gemini instead of the baseline

Set `GOOGLE_API_KEY` or `GEMINI_API_KEY` in your shell, then start a new server:

```sh
CAPSTONE_PROVIDER=gemini python -m uvicorn api:app --host 127.0.0.1 --port 8120
```

Each supported question makes one Gemini 3.8 Flash generation request. The
adapter allows four requests per server process, LOW thinking and at most 1,024
output tokens each, with a 35-second provider timeout and no retries or tools.
An unknown question with no retrieval hits makes no request. The model can still
produce an incorrect explanation: source-ID and exact-quote validation do not
check every claim in its answer. Inspect the quotes and the underlying document.

## Understand the implementation

- `assistant.py`: immutable passages, BM25 over eligible text, one optional alias
  refinement, up to three source reads, byte-bounded context, retrieval cache,
  concurrency admission and answer validation.
- `api.py`: FastAPI service, demo-token mapping, bounded JSON input and source reads.
- `providers.py`: extractive-compatible Gemini structured-answer adapter.
- `static/`: local UI; no remote scripts, model calls or API key in the browser.
- `docs/`: eight fictional documents across two versions and two collections.
- `cases.json`: development application cases. They are authored with this lab,
  not held-out cases or a measurement of production answer quality.
- `evaluate.py` and `release_check.py`: offline cases and a local release manifest.

Cache keys include principal, role, version, collection, question and corpus
snapshot. Grants are checked before looking in the cache, and source reads check
access again. The cache stores retrieval candidates, not generated answers;
its defaults are 32 entries and a 60-second TTL. The server admits two concurrent
answer requests and returns HTTP 429 for another request while both are busy.
These are limits in one process, not a distributed rate limiter.

The context bound counts the UTF-8 bytes of serialized source IDs and passages.
It is **not** a tokenizer or the model's input-token count. The question,
instructions and JSON wrapper consume additional input. Documents are small and
loaded at startup; changing them requires a new process. Use the ingestion,
vector-retrieval and tokenizer labs when extending this capstone to a larger corpus.

## Run the offline checks

```sh
python -m unittest discover -v
python evaluate.py --output runs/local-docuctl/evaluation.json
python release_check.py seal --manifest runs/local-docuctl/release.json
python release_check.py verify --manifest runs/local-docuctl/release.json
```

The release check recomputes the extractive application cases and compares source,
UI, document and case hashes. It does not deploy a service or certify the Gemini
answers. Keep the earlier manifest if comparing an existing release; overwriting
it accepts a new local baseline after review.

## Reproduce the HTTP demo

```sh
python record_demo.py --output runs/my-http-demo.json
```

This starts a real loopback Uvicorn process, sends the seven documented activities,
then stops it. The saved default run is `runs/http-demo.json`. The recorder uses
inherited file descriptors; use the manual server and CLI if your platform does
not support `pass_fds`.

Gemini preflight prints the four exact requests without loading credentials:

```sh
python record_demo.py --provider gemini
```

Only execute a new paid run deliberately:

```sh
python record_demo.py --provider gemini --execute-approved --output runs/my-gemini-demo.json
```

That mode requires a process alarm, stops at 170 seconds plus up to five seconds
of shutdown, and preserves provider replies or failures under the chosen output
folder. Default offline tests never run it. Runtime records and text outputs are
included so the lesson can show the actual result without terminal screenshots.

## Recorded runs

`runs/local-docuctl/` contains fresh extractive HTTP results and application checks against `docs/`. `runs/gemini/` contains four real generated responses from the same corpus. Public provider projections omit opaque signature fields and link their execution details. These examples do not establish quality on other questions.
