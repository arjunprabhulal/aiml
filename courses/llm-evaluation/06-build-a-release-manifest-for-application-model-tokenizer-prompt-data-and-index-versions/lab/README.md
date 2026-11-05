# Bind a tracker evaluation to a local release manifest

This deterministic lab reads the unchanged tracker docs-assistant sources,
recording and evaluation report from the published per-stage evaluation lesson.
The copied files are under `bundle/`; `requirements.lock` there is the original
runtime dependency list, not a claim that every historical dependency was
independently verified. `run-config.json` contains the recorded generator,
embedder, judge and strict-faithfulness settings.

```
python3 -m venv .venv
.venv/bin/python -m pip install -r tracker-requirements.txt
.venv/bin/python -m pytest -q test_release.py
.venv/bin/python record_release_checks.py --check
.venv/bin/python bind_release.py verify
```

No model calls or cloud resources are used. Running the recorder without
`--check` rewrites the manifest and compatibility scenarios. It never recomputes
answer-quality scores. The historical Gemini output retains all its failures.
`bind_release.py build` refuses a recording whose key or case membership differs
from the current inputs; changing documentation requires a fresh model run and
evaluation in the source lab, not just a new manifest.

The file hashes detect later differences from this locally created manifest.
They do not attest that this code produced the earlier recording, authenticate
the publisher, identify hosted model weights, inspect a deployment, or prove
answer quality. A person can modify both files and an unsigned manifest.
The original s28 `release.py` is retained as `legacy/legacy_release.py`; its old-domain
outputs are not reused as tracker results.
