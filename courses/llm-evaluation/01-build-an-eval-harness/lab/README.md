# Build an eval harness with pytest

Python 3.11 or later. Live runs call Gemini `gemini-3.8-flash` and need `GOOGLE_API_KEY`; replays and `test_harness.py` need no model and no key.

```bash
pip install -r requirements-lock.txt
export GOOGLE_API_KEY=...                    # live runs only
pytest -q --live test_triage.py --json-report --json-report-file=runs/gemini-3.8-flash-v1.json
pytest -q test_triage.py                     # replay the recording, no model call
pytest -q test_harness.py                    # offline tests of the harness itself
python repeat.py                             # 5 live trials per case: pass@k and pass^k
```

Local alternative: `ollama pull gemma4:e2b`, then prefix any command with `TRIAGE_MODEL=gemma4:e2b`. The judge follows the model. `recordings/gemma4-e2b-v1.json` holds a recorded Gemma run, so `TRIAGE_MODEL=gemma4:e2b pytest -q test_triage.py` replays it.

- `triage.py`: the function under test. The model labels a GitHub issue, sets a priority and writes a summary.
- `dataset.json`: the versioned cases. `harness.py` validates them and records each model and judge reply.
- `conftest.py`: the `--live` option, the recording key and the judge model.
- `test_triage.py`: deterministic checks and one DeepEval G-Eval judge with its calibration test.
- `recordings/`: the recorded model and judge replies. `runs/`: the JSON reports and console output of each run.

The Gemma run fails 2 tests: they are real model errors that the lesson discusses, and its replay must reproduce them. `conftest.py` sets `DEEPEVAL_TELEMETRY_OPT_OUT=1` to keep DeepEval from sending telemetry.
