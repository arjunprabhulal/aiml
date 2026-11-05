# Compare full updates and low-rank adaptation

Python 3.12+, standard library only. No API key, model download or GPU.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python adapt.py
python -m unittest -v test_adapt.py
```

This trains a small bag-of-words intent classifier using full or low-rank updates. It is not an LLM fine-tuning or QLoRA benchmark. The output reports exact feature-vector overlap between train.json and heldout.json; the small fixture demonstrates the mechanism rather than generalization.

run-output.txt contains the saved local output. run-metadata.json binds the source, tests, input files and output by SHA-256.
