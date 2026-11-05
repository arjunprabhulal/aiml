# Tracker evaluation split checks

The current lesson uses `tracker_leakcheck.py`, `split_models.py`, and
`record_tracker_splits.py`. `tracker-dataset.json` is an unchanged copy of the
published evaluation harness's fictional tracker issue set; `perturb.py` is
unchanged from the robustness lesson. The recorded split adds two shouting
variants and groups each with its original using scikit-learn.

```
python3 -m venv .venv
.venv/bin/python -m pip install -r tracker-requirements.txt
.venv/bin/python -m pytest -q test_tracker_splits.py
.venv/bin/python record_tracker_splits.py --check
.venv/bin/python tracker_leakcheck.py tracker-splits.json --lock tracker-heldout.lock.json
```

No model, network, or API key is needed after package installation. Running the
recorder without `--check` rewrites its three outputs. `tracker-split-run.json`
is a local deterministic run, not a model evaluation or an estimate of leakage
prevalence. Near word overlap and copied prompt excerpts request review; they
cannot establish how information reached an application. Exact normalized
cross-split inputs, explicit ancestry crossings, and frozen split edits block.
A pass does not establish unseen training data or detect semantic paraphrases.

The `legacy/` directory preserves the earlier inbox example and its saved files.
Use the tracker commands above for this lesson.
