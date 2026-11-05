# Build a next-token prediction baseline

Python 3.10 or newer. This complete lab uses only the standard library; no API key,
model download, GPU or package installation is needed.

Extract the ZIP and open `build-a-next-token-prediction-baseline/`. On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python trace_baseline.py
python -m unittest -v test_baseline.py
```

On Windows, create the environment with `py -m venv .venv` and activate it with
`.venv\Scripts\Activate.ps1` in PowerShell. Keep all bundled Python modules,
corpus/tokenizer files and JSON fixtures together. Source panels in the lesson
import these files directly.

The `trace_*.py` programs print local results. `--check` compares deterministic
results with the bundled record; `--write` replaces that record. Timing varies
between runs and is recorded separately from deterministic checks.

## Inspect the split

Run `python3 inspect_split.py` before fitting the baselines. `split-overlap.json` records exact story-text matches across the original row splits: 5 development rows and 5 test rows match training text; 8 test rows match training or development. Rows are disjoint by position, but their text is not. The tokenizer also saw the whole corpus. Preserve this split to reproduce the original scores. For a new experiment, deduplicate or group identical stories before splitting and train the tokenizer only on training text.
