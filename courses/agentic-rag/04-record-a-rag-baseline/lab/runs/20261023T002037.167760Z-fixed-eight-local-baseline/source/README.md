# Record a RAG Baseline

Retrieval Results, Answer Checks, and Run Settings.

This preparation reuses the fixed RAG pipeline, the frozen eight-case documentation dataset, and the existing Evals runner. It is not an agent loop or a new evaluation framework. **No fresh baseline has been recorded yet. Root must review the exact code and metrics before local inference.**

Use the already prepared Python 3.12 environment. Do not install dependencies or download weights for this preparation.

```sh
python baseline.py plan
python -m unittest -v test_dataset test_baseline
```

`plan` is offline and defaults to four development cases. The other four fixtures are public held-out teaching cases, not unseen external test data. Inspect the plan for both splits without running a model:

```sh
python baseline.py plan --split development --split held_out --include-held-out
```

After root independently reviews and explicitly authorizes this exact code, the operator may use the returned code hash:

```sh
python baseline.py record --fresh-local --reviewed-code-sha256 REVIEWED_HASH \
  --split development --split held_out --include-held-out --trials 1 \
  --out runs/NEW_UTC_DIRECTORY
```

The hash binds reviewed source; it is not authentication or permission. Do not execute that command merely because a hash can be computed. Existing output directories are refused. The parent starts an isolated child without inherited provider credentials. Only existing Ollama loopback endpoints are allowed. No model pulls, hosted calls, silent retries, output repair or judge calls are permitted.

The full plan allows one Qwen embedding request containing four passages, eight query-embedding requests and at most eight Gemma requests: 17 inference HTTP attempts. Each question gets one trial. Gemma retains the preceding configuration: temperature 0, `num_predict=400`, and the same `Reply` schema. A missing/changed installed model digest stops the run. Timeouts and invalid JSON are retained; neither causes a second generation.

The three original source summaries and a documented-only Python 3.13 summary form the frozen corpus. The unchanged pipeline still uses the existing splitter, cosine vector store, top two passages, prompt, answer shape and source checks. It receives the exact question and retrieved text, never expected labels or oracle version tags. The new corpus/query vectors must be real local model outputs; the old two-query replay cannot answer these eight questions.

The live recorder executes once. Evaluation uses the saved recording:

```sh
python baseline.py replay --record runs/RECORDED_DIRECTORY
```

Retrieval metrics compare exact annotated chunk IDs, including version-specific identities. Unsupported cases have no positive target and receive null retrieval metrics. With one target per supported case, recall at two equals Hit@2, so they are not separate findings. Reply shape, expected status and target-source alignment are automatic checks. A valid source ID does not show that a factual claim follows from the passage. `human-review.json` starts unreviewed and is never filled automatically. Save any completed human review separately, bound to its answer and rubric hashes.

Fresh output retains the run plan, actual requests/responses, per-case events, vectors, parser errors, usage fields when supplied, real elapsed times, stdout/stderr and source hashes. Missing usage stays missing. Eight authored questions and one trial do not establish general accuracy, deterministic behavior, performance percentiles or a security guarantee. Review screenshots and lesson prose come only after the actual result is reviewed.

The copied pipeline files, dataset adapter/fixtures and Evals core are checked against `baseline-source-versions.json`. The only roadmap-reference update records the coordinator's revised status and 35-lesson count; dataset and source-target hashes are unchanged. No existing pilot, dataset or public lesson is overwritten.

Original application and authored fixtures are MIT licensed as in the existing labs. Model weights are not distributed. No publication or hold change is authorized by this preparation.
