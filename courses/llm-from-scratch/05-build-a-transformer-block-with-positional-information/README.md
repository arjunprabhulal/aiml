<img src="../../../assets/icons/llm-from-scratch.svg" width="20" height="20" alt=""> [Build a Small Language Model From Scratch](../) · lesson 5 of 11

# Build a transformer block with positional information

[![Build a transformer block with positional information](lesson.png)](https://aiml.sh/courses/llm-from-scratch/build-a-transformer-block-with-positional-information/)

Combine causal attention, normalization, skip paths and a feed-forward network. Add position embeddings and check the complete block’s gradients.

- **Full lesson:** [https://aiml.sh/courses/llm-from-scratch/build-a-transformer-block-with-positional-information/](https://aiml.sh/courses/llm-from-scratch/build-a-transformer-block-with-positional-information/)
- **Reading time:** 30 min
- **Uses:** Standard library only

## Lab

The [`lab/`](lab/) folder holds the complete runnable code, tests and recorded outputs, the same files as the lesson's download on aiml.sh. The lesson explains each step.

### Lab notes

#### Build a transformer block with positional information

Python 3.10 or newer. This complete lab uses only the standard library; no API key,
model download, GPU or package installation is needed.

Extract the ZIP and open `build-a-transformer-block-with-positional-information/`. On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python trace_block.py
python -m unittest -v test_model.py
```

On Windows, create the environment with `py -m venv .venv` and activate it with
`.venv\Scripts\Activate.ps1` in PowerShell. Keep all bundled Python modules,
corpus/tokenizer files and JSON fixtures together. Source panels in the lesson
import these files directly.

The `trace_*.py` programs print local results. `--check` compares deterministic
results with the bundled record; `--write` replaces that record. Timing varies
between runs and is recorded separately from deterministic checks.
