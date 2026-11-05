# Generate traces and grade evaluations with agents-cli eval

This is the complete `agents-cli-eval-grade` teaching lab. Extract it and begin in this directory. Install Python 3.12+ and uv before running the commands below.

Keep the generated project from Lesson 1. Replace `/absolute/path/to/docuctl-docs` with its real path. The extracted lab and generated project are different directories.

## Commands, in lesson order

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
LAB_DIR="$PWD"
```

```bash
export PROJECT_DIR="/absolute/path/to/docuctl-docs"
cd "$PROJECT_DIR"
mkdir -p tests/eval/datasets
cp "$LAB_DIR/docuctl-eval-dataset.json" tests/eval/datasets/docuctl-eval.json
cp "$LAB_DIR/eval_config.yaml" tests/eval/eval_config.yaml
```

```bash
# Generate populated traces against the local ADK server
agents-cli eval generate \
  --dataset tests/eval/datasets/docuctl-eval.json \
  --output artifacts/traces/docuctl-traces.json \
  --concurrency 2
```

```bash
agents-cli eval grade \
  --traces artifacts/traces/docuctl-traces.json \
  --config tests/eval/eval_config.yaml \
  --output artifacts/eval_results \
  --project "$GOOGLE_CLOUD_PROJECT"
```

```bash
cd "$LAB_DIR"
"$LAB_DIR/.venv/bin/python" -m unittest -v test_eval_grade.py
```

## What the checks establish

Offline tests exercise local helpers and supplied examples. They do not invoke Gemini, deploy infrastructure, register an agent or verify telemetry delivery. Model-generation commands can incur charges; deployment and registration require your own cloud resources and credentials.

`docuctl-traces.json` contains the actual three-case agent run; `docuctl-results.json` contains the corresponding custom-function grading. These metrics check selected strings and newly generated turns, not factual correctness.
