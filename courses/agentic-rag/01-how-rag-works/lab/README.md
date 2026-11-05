# How RAG works

A small original Python documentation example for **Building Agentic RAG Applications**. This first lab is a fixed retrieval pipeline, not an agent loop.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/pip install --no-deps -e .
.venv/bin/python rag.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python exercise.py path-read
.venv/bin/python exercise.py path-write
```

The first exercise command intentionally returns exit status 1 with a hint. The second returns 0 after selecting the writing passage.

Replay uses actual saved Qwen vectors and Gemma replies, so it needs no model server. Unknown embedding inputs raise an error: replay does not generate new answers. To make a fresh local run, install the model tags listed in record_run.py separately, then run `python record_run.py`. That command verifies they are present and never downloads weights. It replaces the named sample run. No cloud account, API key, hosted service or PostgreSQL server is used.

`src/agentic_rag/concepts.py` uses LangChain's splitter and in-memory vector store; the application checks source IDs and skips generation when retrieval is empty. It does not check whether an answer follows from the passage. The runs folder contains actual local requests, vectors, structured replies, model digests, package versions and console output. There is one model run per question, not a quality or performance benchmark.

The data folder contains original concise explanations of Python APIs, not copied documentation passages; its source manifest links the official documentation. The sample index contains these three short passages only. There is no reranker, agent search loop, persistent store, HTTP app or production privacy system in this pilot.

The package is MIT licensed. LangChain integrations are MIT licensed. Qwen3-Embedding-0.6B and Gemma 4 E2B IT model cards identify Apache 2.0; weights are not included. Python documentation uses the PSF License Agreement. Reference URLs and verification date are in the lesson and source manifest.

Run `python report.py` to render the saved local model record as HTML. The included desktop and phone PNGs are genuine high-resolution Chrome captures of that report, explicitly labelled saved output. They are lesson media, not new inference or screenshots of a fabricated terminal. The source manifest binds them to the raw record and records capture dimensions/date.

## Start with the failed baseline

```sh
python baseline_example.py
```

This is offline inspection of the original `utf8-write` baseline, copied byte for byte from the frozen eight-case run. It prints the two reading passage IDs, `not_in_docs`, the model's saved decline and empty source links. It makes no inference request and does not rewrite the file. `rag.py` remains the separately labeled earlier concept replay, whose question retrieved the writing passage and answered successfully; it is not a rerun or repair of this baseline.
