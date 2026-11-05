# User-return prediction: one manual MLOps workflow

Local review lab for the six-stage Building MLOps syllabus. Python 3.12 or later,
standard library only. No API key, model download, GPU, database server or paid
service. The fixture contains fictional users; it does not contain personal data.

## The application

At noon UTC, estimate whether an existing user returns during the next 24 hours.
A product analyst consumes the predictions in a daily review. This lab does not
send messages or take actions on users. Its one feature is the number of events
known in the preceding 24 hours. A return label becomes available after the full
outcome window plus the fixture's two-hour reporting delay.

This is a deliberately small learning task. The synthetic labels illustrate the
workflow; the scores do not measure usefulness for a real product. A real project
must justify the prediction target, data collection and action before deployment.

## Run the complete manual workflow

Unzip the download and enter `mlops-return-workflow/`. Use a new output directory
for each attempt; existing artifacts are never overwritten.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python workflow.py prepare --out work/cohort.json
python workflow.py train --cohort work/cohort.json --out work/candidate.json
python workflow.py evaluate --cohort work/cohort.json --model work/candidate.json --out work/validation.json
python workflow.py predict --model work/candidate.json --event-count 3
python -m unittest -v test_workflow.py
```

On PowerShell use `.venv\Scripts\Activate.ps1` to activate the environment.
`predict` starts a new process and loads the saved full-precision weights and
training-fitted scaler. `candidate.json` is a model, not just an evaluation report.
The evaluation command defaults to validation. `--split test` is available for
one final evaluation after model choices are fixed; the saved walkthrough does
not evaluate test data or select settings using it.

## Existing code reused

`vendor/availability.py` is copied unchanged from the published data-availability
lab. It excludes events that arrived after prediction and labels not ready at
dataset assembly. `vendor/baseline.py` is copied unchanged from the published
supervised-baseline lab. The adapter configures its feature/class names before
calling its existing scaling and logistic-fitting functions. It does not load
Rice CSV data or present earlier Rice outputs as user-return measurements.

`make_fixture.py` generates the original deterministic fixture. The event log
contains feature-window events, including one deliberately late event per
observation. Labels are separately authored finalized records from an assumed
complete outcome collector; they are not inferred from that partial event log.

The time split evaluates later observations for the same user population:
training January 3–8, validation January 10–11, test January 13–14, 2026.
January 9 and 12 separate the 24-hour outcome windows. This is not an unseen-user
evaluation. Preparation uses the fixed assembly cutoff stored in `scenario.json`.

## Read the output

`recorded/` contains an actual local execution of the four commands. Source and
fixture identities, Python version, and the command list are in
`recorded/run-metadata.json`. Re-run into `work/`, not `recorded/`, then compare
the numerical model and evaluation values. Output path strings will differ.

## Failure checks

The tests execute the actual assembler, fitting adapter, exported model and
fresh-process prediction command. They cover late events, pending labels,
training-only fitting, invalid counts/labels, duplicate observations, changed
cohort identity, inconsistent split assignments, malformed models and refused
artifact overwrites. These tests do not measure model quality or service load.

## What follows in the syllabus

The manual workflow establishes the data-to-prediction path. The platform
workshops below connect that same model to local MLflow tracking and registration,
Prefect orchestration, batch/HTTP prediction, release controls and monitoring.
These are local teaching implementations; no cloud deployment or hosted CI job
was run. Original historical course records remain unchanged.

## Shared-application adaptations

Run the manual workflow first into `work/`. Then run these commands in order:

```bash
python adapt.py availability
python adapt.py splits
python adapt.py costs --cohort work/cohort.json --model work/candidate.json
python adapt.py validation --work work/adaptations
python adapt.py history --work work/adaptations
python adapt.py parity --work work/adaptations
python adapt.py versioning --work work/adaptations
python -m unittest -v test_workflow.py test_foundations.py
```

The original split, quarantine, history, SQL lookup and feature-calculation
implementations are copied into `vendor/`, `quarantine_reuse.py`,
`history_reuse.py` and `join.sql`. `foundations.py` supplies the shared application's
date windows and explicitly materializes zero activity for its known users; an
unknown user remains missing. All 240 historical counts are compared with the
manual assembler. The old store key `user_events_1d@v1` maps explicitly to the
model feature `recent_event_count`.

`recorded-adaptations/` retains new actual local outputs, separate from the
original `recorded/` manual run. Cost values are illustrative policy assumptions.
The threshold comparison does not change the saved model's 0.5 decision rule or
open final test outcomes. The platform section below documents the installed,
pinned MLflow/Prefect integration and its actual local execution records.

The initial adaptation capture is preserved under `recorded-adaptations-initial/`
with its original source snapshot. The active records were rerun after correcting
the ingestion wrapper so malformed source events reach quarantine instead of
failing before preservation. The regression suite also exercises a real partial
version-binding attempt and checks that SQLite rolls it back.

## Local platform workshops: tracking, automation, release and operation

The first manual run and seven adaptations use the standard library. The next
workshops add the actual local MLflow and Prefect integrations, followed by a
batch consumer, an optional loopback HTTP interface and local release control.
Install their exact dependency set in the isolated environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-platform.txt
python -m pip check
python tracking.py --workspace work/tracking --out work/tracking.json
python -m unittest -v test_tracking.py
```

MLflow telemetry and Prefect server analytics are disabled. Prefect's temporary
local server keeps its state under a temporary-directory `user-return-prefect`
folder by default. Set `RETURN_PREFECT_HOME` before running a command to choose
another writable local state directory. Model artifacts and application receipts
remain in the explicit workspace supplied below. No Prefect Cloud configuration,
paid API, model download or GPU is needed.

Run the twelve workshops in this order, in the same extracted lab directory:

```bash
python course.py pipeline --workspace work/course
python course.py retries --workspace work/course
python course.py ci-checks --workspace work/course
python course.py candidate-gate --workspace work/course
python course.py registry --workspace work/course
python course.py serving --workspace work/course
python course.py rollout --workspace work/course
python course.py rollback --workspace work/course
python course.py monitoring --workspace work/course
python course.py delayed-evaluation --workspace work/course
python course.py drift --workspace work/course
python course.py recovery --workspace work/course
```

Each command writes its JSON result under `work/course/` and prints the actual
result. Retain that directory. Topic outputs use exclusive creation; another full
sequence uses a new workspace such as `work/course-2`. The retry workshop itself
checks safe reuse of an identical completed fit. An interrupted attempt remains
available for inspection instead of being silently replaced.

Run all local contracts and platform integrations with:

```bash
python ci.py --out work/ci-result.json
```

`ci.yml` is an optional GitHub Actions workflow for a repository containing this
lab at its root. Copy it into `.github/workflows/` if adopting that setup. The
hosted job was not dispatched here; the equivalent local checker was executed.
A Docker image and public deployment were not built. The registry uses a custom
`user_return` MLflow flavor and `release.load_bundle`, not `mlflow.pyfunc`.

`serving.py` defaults to batch prediction. The course also starts and stops a
fresh uvicorn process on loopback to check HTTP parity and rejection. Persistent
local examples, after the serving workshop creates its requests:

```bash
python serving.py --bundle work/course/bundle-v1 --input work/course/requests.json --out work/daily-predictions.json
python serving.py --bundle work/course/bundle-v1 --http --port 8766
```

The rollout table routes local calls between two actual run bundles. Their fitted
parameters are equal: this tests version control and operational behavior, not a
quality improvement. The rollback drill temporarily moves the selected candidate
directory, observes the actual missing-file error, restores the stable routing
configuration and then puts the candidate directory back. It preserves artifact
bytes and the append-only release history.

Service timings describe the actual bounded local calls, excluding model loading
and network transport. Delayed evaluation supplies fixture times to the authored
outcome records; it does not claim newly observed user behavior. The drift sample
of all zero counts is deliberately controlled and has no newly collected labels.
The recovery fit uses the original valid source and the unchanged candidate gate;
it does not automatically promote or change traffic. No fitting, policy selection or quality report uses the reserved final-test outcomes.

`recorded-platform/` retains the actual command results, source/dependency hashes,
raw command logs and the application workspace from the local execution. Run IDs,
bundle identities and timings vary across executions. Historical workspaces may
contain the original absolute file locations in backend metadata; do not execute
those retained workspaces as a portable installation. Run the commands above into
a fresh workspace. Original manual and seven-adaptation recordings remain intact.

`recorded-platform-initial/` preserves the first complete platform run and its source snapshot before the equivalent-UTC outcome-join repair. The active `recorded-platform/` run includes that repair and its regression test.
