# Create an evaluation set and a failure taxonomy

Python 3.12 or later; standard library only. This lab reuses the reviewed local
architecture.py and pages.json from ai-system-architecture. It executes a Python
lookup/proposal function and five authored single-fault probes, not a model.

Extract the complete ZIP and enter ai-system-evaluation/:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python evaluate_cases.py
python evaluate_cases.py --check
python -m unittest -v test_evaluation.py
```

PowerShell activation: .venv\Scripts\Activate.ps1.
Use --save my-report.json for a separate report with actual execution timings.

cases.json has 12 authored development cases. Expected commands and sources are
written independently of the function output. Required refusals are successful
outcomes; no output remains incomplete. Reports preserve all cases and summarize
version, environment, role and operation slices. Slices overlap across dimensions.
They are not independent populations or estimates of deployed failure rates.

vendor/harness.py is an unchanged copy of the existing generic standard-library
harness in public/examples/build-acceptance-fixtures-from-a-spec/harness.py. It
owns case loading, version hashes, trials, verdicts and run records. task.py only
adds application-specific checks. See run-metadata.json for source hashes and
provenance. No provider adapter, model judge or new evaluation runner is built.

Faults: wrong source, permission bypass, omitted approval, missing output field
and no output. These are deliberately injected defects, not recorded model mistakes.
A boundary tag is the first failed check, not a proven root cause or a complete
list of simultaneous failures. All cases are visible development fixtures;
there is no held-out performance claim or production deployment.

result.json is an actual local run record. --check ignores only the existing
run-description fields at their known record locations (per-trial timings and
manifest timestamp/environment), while
checking outcomes, source hashes, graders, cases and slices. No API key, network
request, model download, GPU job or package installation is needed.
