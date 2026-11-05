# Define a task-specific answer rubric

A Python 3.12+ standard-library exercise using the existing evaluation runner.
Eight answers and their example judgements are authored fixtures. They are not
model responses, human-study results or evidence of a model's accuracy.

## Run

Unpack the complete lesson ZIP and enter `ai-system-answer-rubric/`:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python evaluate_rubric.py
python evaluate_rubric.py --check
python -m unittest -v test_rubric.py
```

No packages, keys, downloads, services or model calls are needed. The first command
applies supplied judgements and runs completed decisions through the unchanged
harness. It does not perform semantic judgement automatically. The experiment
uses temporary case files and preserves bundled records. Save a separate run with:

```sh
python evaluate_rubric.py --save my-rubric-run.json
```

## What the result means

- Eight development answers address the same fictional docuctl 3 staging task.
- Six have complete, determinate judgements: three accepted, three rejected.
- One answer has an uncertain support judgement and one has no judgement fixture.
  Both remain pending and outside the scored harness subset. Coverage still
  includes them. Pending review is distinct from missing application execution.
- The known bad answers intentionally fail the rubric. The 20 implementation tests
  should all pass because they check those expected decisions and failure guards.

The rubric first requires all criterion judgements with no uncertainty. An
unfinished review stays pending even if another criterion already indicates a
failure; its existing ratings remain visible. Completed reviews reject any
`does_not_meet`, and accept only when every criterion `meets`. This is the
exercise's explicit decision policy, not a universal rubric protocol.

## Files

- `source.txt`: short fictional guide; no command is executed.
- `rubric.json`: task, five required criteria, source reference quotes and rule.
- `cases.json`: questions, authored answer text/citation, required acceptance and
  exact source/rubric/review revision bindings. All cases are development fixtures.
- `annotations.json`: authored criterion ratings, reasons, source quotes and
  relevant answer spans. The absence of a review is intentional for one case.
- `rubric.py`: validate bindings/excerpts and apply the completed-review rule.
- `task.py`: adapt completed decisions to the existing runner's grader interface.
- `evaluate_rubric.py`: retain full coverage; run only determinate decisions;
  retain original answer text and ratings in per-trial metadata.
- `vendor/harness.py`: unchanged from the earlier AI Systems evaluation lab and
  published evaluation-runner implementation. No second runner is introduced.
- `test_rubric.py`: 20 offline tests, including stale judgements, pending coverage,
  altered source/rubric/answer/question, missing criteria and invalid references.
- `result.json`, `run-output.txt`, `run-metadata.json`: actual local records and
  provenance hashes, with the authored-fixture mode stated.

## Revision and judgement boundaries

Reviews bind the answer content, source and rubric hashes. Cases bind the review
revision too. Editing a label is an explicit new fixture expectation, not an
unnoticed correction to an existing measurement. The full case-set hash stays in
the result; the harness's case-set hash describes its actual six-case subset.

The code confirms that a quoted source fragment matches the required criterion
reference and that any supplied answer span occurs in the answer. Spans may be empty when
no excerpt is supplied, including an omitted requirement. These checks do
not establish entailment, completeness or the truth of the supplied judgement.
Changing an incorrect label and updating its revision can still produce an
incorrect assessment. Real usage needs reviewed annotations and adjudication.
There is no human agreement estimate, model judge, calibrated semantic classifier,
held-out claim, latency benchmark or model improvement claim in this lab.

`--check` ignores only run timestamps, environment descriptions and per-trial
latency in their known report locations. Input hashes, ratings, coverage, answer
text and decisions must still match. Dependencies and code-run identity remain
with the existing harness; this article owns the task-specific rubric and its
interpretation, not a new generic evaluator or agent-trace curation pipeline.
