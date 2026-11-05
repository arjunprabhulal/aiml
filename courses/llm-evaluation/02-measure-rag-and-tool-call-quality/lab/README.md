# Measure RAG and tool-call quality

Python 3.11 or later. Live runs call Gemini `gemini-3.8-flash` and `gemini-embedding-2` and need `GOOGLE_API_KEY`; replays and `test_evaluate.py` need no model and no key.

```bash
pip install -r requirements-lock.txt
export GOOGLE_API_KEY=...                  # live runs only
python evaluate.py --live                  # run the agent and the judge, record both, write runs/report.*
python evaluate.py                         # rebuild the report from the recording, no model call
python calibrate.py                        # replay the judge calibration (--live to rerun it)
python assistant.py "Is issue 212 fixed?"  # one live question
pytest -q test_evaluate.py                 # offline tests of the evaluation code
```

Local alternative: `ollama pull gemma4:e2b qwen3-embedding:0.6b`, then set `DOCS_MODEL=gemma4:e2b DOCS_EMBEDDER=qwen3-embedding:0.6b`. The judge stays `gemini-3.8-flash`; change `JUDGE_MODEL` in `evaluate.py` to judge locally too.

- `assistant.py`: the system under test, a LangChain agent with `search_docs` over an `InMemoryVectorStore` and `get_issue`.
- `docs.json`, `issues.json`: the documentation pages and issues the tools read. `cases.json`: the questions with expected tools, expected pages and a reference answer.
- `evaluate.py`: scores tools, retrieval and DeepEval's judged metrics per case and names the first failing stage.
- `calibrate.py` and `calibration-cases.json`: answers and contexts with a known defect, scored three times each.
- `cassette.py`: record/replay that refuses a recording whose key differs; `recording_key()` in `evaluate.py` hashes the cases, pages, issues and system prompt into the key. `recordings/` and `runs/`: the recorded traces, verdicts and reports.

`evaluate.py` and `calibrate.py` set `DEEPEVAL_TELEMETRY_OPT_OUT=1` to keep DeepEval from sending telemetry.
