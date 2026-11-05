# Repeated-trial benchmark that records failures and incomplete runs

Python 3.11 or newer, standard library only. Tested with Python 3.11 and 3.15. The tests never call a model: they replay the logs in `recorded/`. Recording again needs a local [Ollama](https://ollama.com) server with `gemma4:e2b` and `qwen3.5:0.8b` installed at the digests pinned in `model_triage.py`.

- `harness.py`, `triage_task.py`, `cases.json`: unchanged copies from the versioned evaluation harness build.
- `model_triage.py`: inbox triage by a local model at temperature 1, with seed 1000 + trial number.
- `bench.py`: runs every development case for k trials in trial-major order, appends each trial to a JSON Lines log as it finishes, resumes a stopped run from its log, stops at a time budget, and converts a log to a harness recording in which unrun trials are `NotRun` errors.
- `outputs_digest.py`, `recorded/recordings.json`: a SHA-256 digest of every trial's output per log, kept for every recording of the logs, so two recordings can be compared without keeping both.
- `report.py`: verdicts, failures by check, incomplete trials by error type, pass counts per case, flaky cases, pass@k and pass^k for every k, and latency.
- `recorded/gemma.jsonl`, `recorded/qwen.jsonl`: the benchmark logs. `recorded/gemma-partial.jsonl`: the gemma log as it was when the 30-second budget stopped the first run.
- `recorded/*.json`: the logs converted to harness recordings. `runs/`: harness run records and the reports.
- `test_bench.py`: `python3 -m unittest -v test_bench.py`

Rebuild the recordings, run records and reports from the logs, without a model:

```bash
python3 bench.py --log recorded/gemma.jsonl --convert recorded/gemma.json
python3 bench.py --log recorded/qwen.jsonl --convert recorded/qwen.json
python3 bench.py --log recorded/gemma-partial.jsonl --convert recorded/gemma-partial.json
python3 harness.py run --task triage_task --cases cases.json --system replay:recorded/gemma.json --split development --trials 10 --out runs/gemma.json
python3 harness.py run --task triage_task --cases cases.json --system replay:recorded/qwen.json --split development --trials 10 --out runs/qwen.json
python3 harness.py run --task triage_task --cases cases.json --system replay:recorded/gemma-partial.json --split development --trials 10 --out runs/gemma-partial.json
python3 report.py runs/gemma.json runs/qwen.json --out runs/report.json
python3 report.py runs/gemma-partial.json --out runs/report-partial.json
```

Record the logs again (calls the local models):

```bash
python3 bench.py --system model_triage:gemma --trials 10 --log recorded/gemma.jsonl --budget-s 30 --hardware "Apple M4 Pro (Mac16,7), 48 GiB unified memory, macOS 27.0.1"
python3 bench.py --system model_triage:gemma --trials 10 --log recorded/gemma.jsonl
python3 bench.py --system model_triage:qwen --trials 10 --log recorded/qwen.jsonl --hardware "Apple M4 Pro (Mac16,7), 48 GiB unified memory, macOS 27.0.1"
```

The second command resumes the first: it skips every trial the log already holds. Four fields, `RUN_DESCRIPTION_FIELDS` in `harness.py`, describe the run and change on every rerun: `latency_s`, `recorded_latency_s`, `started_at` and `environment`. Everything else reproduces byte for byte from the logs. The logs were recorded three times on October 20, 2026, with the same seeds; `recorded/recordings.json` keeps each recording's output digests, and they are identical. That is an observation on one machine, not a guarantee.
