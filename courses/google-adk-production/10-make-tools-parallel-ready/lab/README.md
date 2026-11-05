# Parallel function tools: native async agent and programmatic worker pool

Python 3.12+. Docuctl is the demonstration deployment CLI described by the original bundled manual. The docs host is a delayed local fixture, not an external service.

```bash
cd adk-parallel-tools
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
cp docs_checker/.env.example docs_checker/.env
```

Fill GOOGLE_API_KEY privately in docs_checker/.env. The example selects the Gemini API. An already installed Ollama model may be selected with DOCS_MODEL=ollama_chat/gemma4:e2b; no model download is performed.

Terminal 1, from this project with the environment activated:

```bash
uvicorn docs_server:app --host 127.0.0.1 --port 8770
```

Terminal 2, same project and environment:

```bash
source .venv/bin/activate
adk run docs_checker
```

At [user]: ask `Check rollback, hooks, tokens, deploy and canary. Which pages are reachable?`. Inspect fetch_page calls, returned page summaries and the final answer. The native package uses the awaiting async tool. Exit; use `adk web --host 127.0.0.1 --port 8769 .` and select docs_checker to inspect it in the local Dev UI. Startup alone makes no model request; asking a question does. Stop both services with Ctrl-C.

The worker-pool experiment belongs in Python because it passes per-invocation RunConfig. There is no fabricated adk run --workers flag. Set GOOGLE_API_KEY privately and export GOOGLE_GENAI_USE_ENTERPRISE=0 in this terminal; assistant.py does not automatically read docs_checker/.env.

```bash
python assistant.py --tool sync --workers 4 "Check rollback, hooks, tokens, deploy and canary."
```

Choose --tool async, sync or blocking-async. --workers applies ToolThreadPoolConfig to sync tools; it does not move async functions off their event loop. Each fresh command can produce different model calls, so use saved turns for controlled timing comparisons.

```bash
python -m unittest -v test_assistant.py test_native_entrypoint.py
```

Tests replay saved model turns against a local delayed HTTP service. The current recorded-runs.json/run-output.txt contain actual model requests and tool timings from the current sources. Native entrypoint tests use replayed model replies.

Optional author recording: `python record.py --record` asks a live model once, replays its replies for each tool variant, and overwrites the saved run files. Stop the manually started host first; use a separate copy if you intend to record. Without --record it refuses before starting services or models.

Current syntax: https://adk.dev/runtime/command-line/ , https://adk.dev/runtime/web-interface/ , https://adk.dev/tools-custom/performance/ and installed google-adk 2.12.0 RunConfig/ToolThreadPoolConfig.

The fresh model recording used an external operator limit of 8,192 output tokens per provider request. That limit appears in the captured request; it is not a default supplied by `make_agent`. The displayed timings measure tool calls and are not model latency benchmarks.
