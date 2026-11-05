# Paired comparison report with uncertainty and slice-level results

Python 3.11 or newer, standard library only. Tested with Python 3.11 and 3.15. The tests never call a model: they replay the logs in `recorded/`. Recording again needs a local [Ollama](https://ollama.com) server with `qwen3.5:0.8b` installed at the digest pinned in `model_triage.py`.

- `harness.py`, `triage_task.py`: unchanged copies of the evaluation harness at version 3 and the triage task module.
- `cases-robustness.json`: an unchanged copy of the robustness, language and subgroup case set; its development split has 44 cases tagged by source, variant and language.
- `bench.py`: unchanged from the repeated-trial benchmark build.
- `model_triage.py`: the benchmark's model system with two prompts. `qwen_v1` uses the benchmark's prompt; `qwen_v2` adds two sentences.
- `compare.py`: the paired comparison: mean per-case difference with bootstrap intervals over cases, over source groups and over trials, case counts, trial pairs and slices per tag value.
- `recorded/qwen-v1.jsonl`, `recorded/qwen-v2.jsonl`: benchmark logs, 5 trials per development case, seeds 1000 to 1004. `recorded/*.json`: the logs as harness recordings. `runs/`: run records and `comparison.json`.
- `test_compare.py`: `python3 -m unittest -v test_compare.py`

Rebuild every file in `runs/` from the logs, without a model:

```bash
python3 bench.py --cases cases-robustness.json --log recorded/qwen-v1.jsonl --convert recorded/qwen-v1.json
python3 bench.py --cases cases-robustness.json --log recorded/qwen-v2.jsonl --convert recorded/qwen-v2.json
python3 harness.py run --task triage_task --cases cases-robustness.json --system replay:recorded/qwen-v1.json --split development --trials 5 --out runs/qwen-v1.json
python3 harness.py run --task triage_task --cases cases-robustness.json --system replay:recorded/qwen-v2.json --split development --trials 5 --out runs/qwen-v2.json
python3 compare.py runs/qwen-v1.json runs/qwen-v2.json --cases cases-robustness.json --out runs/comparison.json
```

Record the logs again (calls the local model):

```bash
python3 bench.py --cases cases-robustness.json --system model_triage:qwen_v1 --trials 5 --log recorded/qwen-v1.jsonl --hardware "Apple M4 Pro (Mac16,7), 48 GiB unified memory, macOS 27.0.1"
python3 bench.py --cases cases-robustness.json --system model_triage:qwen_v2 --trials 5 --log recorded/qwen-v2.jsonl --hardware "Apple M4 Pro (Mac16,7), 48 GiB unified memory, macOS 27.0.1"
```

The bootstrap uses `random.Random(20261020)` with 2000 resamples, so `comparison.json` reproduces byte for byte. Four fields, `RUN_DESCRIPTION_FIELDS` in `harness.py`, describe the run and change on every rerun: `latency_s`, `recorded_latency_s`, `started_at` and `environment`.
