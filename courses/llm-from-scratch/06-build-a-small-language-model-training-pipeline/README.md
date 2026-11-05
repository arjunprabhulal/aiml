<img src="../../../assets/icons/llm-from-scratch.svg" width="20" height="20" alt=""> [Build a Small Language Model From Scratch](../) · lesson 6 of 11

# Build a small language-model training pipeline

[![Build a small language-model training pipeline](lesson.png)](https://aiml.sh/courses/llm-from-scratch/build-a-small-language-model-training-pipeline/)

Train a one-block transformer on bundled stories using batches and Adam. Inspect loss and compare it with a bigram baseline on held-out stories.

- **Full lesson:** [https://aiml.sh/courses/llm-from-scratch/build-a-small-language-model-training-pipeline/](https://aiml.sh/courses/llm-from-scratch/build-a-small-language-model-training-pipeline/)
- **Reading time:** 30 min
- **Uses:** Standard library only

## Lab

The [`lab/`](lab/) folder holds the complete runnable code, tests and recorded outputs, the same files as the lesson's download on aiml.sh. The lesson explains each step.

### Lab notes

#### Build a small language-model training pipeline

Python 3.10 or newer. This complete lab uses only the standard library; no API key,
model download, GPU or package installation is needed.

Extract the ZIP and open `build-a-small-language-model-training-pipeline/`. On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python trace_train.py
python -m unittest -v test_train.py
```

On Windows, create the environment with `py -m venv .venv` and activate it with
`.venv\Scripts\Activate.ps1` in PowerShell. Keep all bundled Python modules,
corpus/tokenizer files and JSON fixtures together. Source panels in the lesson
import these files directly.

The `trace_*.py` programs print local results. `--check` compares deterministic
results with the bundled record; `--write` replaces that record. Timing varies
between runs and is recorded separately from deterministic checks.
