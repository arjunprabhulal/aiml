# Build a RAG Eval Dataset

Questions, Relevance Labels, and Answerability Checks.

Python 3.12+ is required by the unchanged pinned dependency file. No model server, new model weights or inference is used.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/python build_dataset.py
.venv/bin/python -m unittest -v test_dataset.py
.venv/bin/python render_output.py --html /tmp/rag-dataset-runtime/report.html
```

The renderer executes the validator before rendering actual output. Generated HTML belongs outside public source. Intentional runtime PNGs are genuine 2x desktop/medium/phone captures. The separate `verify_python312.py` behavior probe requires an actual 3.12 interpreter and records selected Python 3.12 facts; 3.13 is documented-only and is not executed by this lab.

- `data/`: four original source summaries, eight authored questions, exact corpus snapshot and frozen held-out lock.
- `rag_dataset.py`/`eval_task.py`: RAG-specific passage/version/hash/answerability checks. Expected handling is an annotation, not a generated model answer.
- `vendor/evals/`: unchanged retained task-independent Evals loader and lock helpers from the site's existing lab. The published tracker adapter remains separate; no tracker-specific schema was relabelled as RAG.
- `pipeline_ids.py`: unchanged ID functions from Build a RAG Pipeline.
- `runs/2026-10-22-dataset/`: actual validation/output/tests, controlled invalid cases, mutation results and output media.

This combines question construction and passage labelling into one usable dataset; baseline retrieval/generation execution is deliberately separate. Valid IDs/hashes cannot prove semantic relevance. The held-out teaching fixtures are public and are not an unseen external benchmark. Missing information means missing from this corpus, not unknowable.

Original question/source summaries and application code MIT. Linked Python documentation retains PSF attribution. No third-party documentation passages, competitor structure or model weights are redistributed. Reuse hashes/licenses are recorded in `source-versions.json`.
