# Measure the work a KV cache removes

Python 3.12+, standard library only. No API key, model download or GPU.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python cache.py
python -m unittest -v test_cache.py
```

This is fixed-weight single-head causal attention using Python lists. The saved operation counts and machine-specific timings come from cache.py. No pretrained language model or GPU is used.

run-output.txt contains the saved local output. run-metadata.json binds the source, tests, input files and output by SHA-256.
