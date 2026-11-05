# Gate releases on eval regressions in CI

Python 3.11 or later. Live runs call Gemini `gemini-3.8-flash` and need `GOOGLE_API_KEY`; the gate, the replays and `test_gate.py` need no model and no key.

```bash
pip install -r requirements-lock.txt
pytest -q test_triage.py --json-report --json-report-file=candidate.json   # replay: prompt v1, dataset v1
python gate.py runs/baseline.json runs/prompt-v2.json                     # exit 0 pass, 1 block, 2 incomparable
pytest -q test_gate.py                                                    # offline tests of the gate
```

`TRIAGE_PROMPT`, `TRIAGE_MODEL` and `TRIAGE_DATASET` select the component under test, for example `TRIAGE_PROMPT=v2 pytest -q --live test_triage.py`. `TRIAGE_MODEL=gemma4:e2b` runs the model under test on a local Ollama server; the judge stays `gemini-3.8-flash` so judged scores stay comparable.

- `triage.py`, `harness.py`, `test_triage.py`: the triage function, harness and eval suite from the harness lesson, with prompt v2 added.
- `dataset.json`, `dataset-v2.json`: version 1 and version 2 of the cases.
- `gate.py` and `policy.json`: the gate and its written policy. `test_gate.py`: offline tests of the gate.
- `eval-gate.yml`: a GitHub Actions workflow that replays the candidate's recording and runs the gate.
- `recordings/` and `runs/`: the recorded replies, the JSON reports, the console output and the gate decisions.

## Documentation stage-report adapter

`stage_report_adapter.py` adapts the separate documentation lesson's saved metrics into gate outcomes; it does not run pytest or a judge. Fixtures under `fixtures/stage-reports/` are exact copies of the original saved reports. It requires matching case/corpus hashes, embedder, k, threshold, adapter mapping and applicability; the existing gate also requires the same judge. Missing metrics, duplicate cases, nonfinite scores and inconsistent first failures are rejected. Not-applicable stages are omitted, never passed. The saved reports omit the full judge prompt and package version; matching judge IDs cannot verify those details. The explicit docs policy makes tool and faithfulness checks critical; `gate.py` and the original triage policy remain unchanged.

Run `python stage_report_adapter.py fixtures/stage-reports/gemini-3.8-flash.json fixtures/stage-reports/gemma4-e2b.json --out runs/my-adapter/result.json`. The actual saved comparison is incomparable (exit 2), because the embedder changed. A blocking comparison exits 1. Even the Gemini report against itself blocks its existing critical pipe-colors faithfulness failure. Never use a known failure as a waiver. This adapter cannot compare documentation scores with issue-triage results or clear the Python retrieval-task gate. `python -m unittest test_stage_report_adapter -v` checks controlled regressions and malformed inputs offline. See `runs/stage-adapter/` for the actual adaptation and provenance.
