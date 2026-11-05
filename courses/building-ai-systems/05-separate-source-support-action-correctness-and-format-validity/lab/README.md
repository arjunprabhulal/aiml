# Separate source support, action correctness and format validity

Python 3.12+ standard library. Start with the task-specific answer-rubric and
AI Systems evaluation-set lessons. Ten authored response fixtures extend the
same fictional docuctl staging question with a structured command proposal.
There are no model responses, external commands or semantic classifier here.

## Run

Unpack the complete ZIP and enter `ai-system-diagnostics/`:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python diagnose.py
python diagnose.py --check
python -m unittest -v test_diagnostics.py
```

No package installation, keys, downloads, GPU or network are needed. Save a
separate result without overwriting an existing file:

```sh
python diagnose.py --save my-diagnostics.json
```

## What each check owns

- Format: parse strict JSON; reject duplicate fields and nonstandard constants;
  require exactly answer/proposal and their required fields/types. A boolean
  must be a boolean, not integer 0. Invalid format rejects the response and
  records the remaining checks as `not_run`, rather than fabricated failures.
- Source: compare answer/proposal citations to the expected guide and reuse the
  existing bound `support` judgement for the unchanged answer. Citation equality
  does not establish semantic support. Changed text needs a new review; missing
  or uncertain review stays pending. A known citation failure remains visible.
- Action: reuse the existing task-result and action-policy checks. The proposed
  command must match r41/staging, `executed` must be false and approval required
  must be true. This checks a proposal's fields, not actual deployment behavior.
- Explanation: retain the complete prior rubric decision. A source-supported
  answer can still omit the required post-rollback health check. Three new passes
  therefore cannot replace the existing task-completeness requirements.

After valid format, an unfinished required review keeps the combined decision
pending, even if another diagnostic already fails; that failure is still visible.
Once reviews are complete, any failed requirement rejects the response. Only all
passes accept it. Invalid format is rejected directly because the dependent
checks cannot run. This is the lab's declared policy, not a universal protocol.

The actual local run produces 1 accepted, 7 rejected and 2 pending fixtures. These
are deliberately chosen contrast cases, not a model quality estimate or a rate
that generalizes to users. Eighteen offline tests cover independent failures,
blocked/pending checks, source/review drift and actual CLI output.

## Files

- `responses.json`: raw authored response strings, response IDs and original
  rubric-case IDs. Some deliberately contain malformed JSON or wrong field types.
- `expected-action.json`: reviewed expected proposal for the fictional guide.
- `rubric-inputs/`: unchanged source, rubric, cases and annotations from the
  answer-rubric lab. Existing revision checks run before diagnostics.
- `vendor/rubric.py`: unchanged rubric binding/decision implementation. A supplied
  answer span must occur in the text; spans are optional when no excerpt is given.
  Quote/provenance checks do not infer entailment or verify annotation correctness.
- `vendor/action_task.py`: unchanged contract/source/task/action checks from the
  evaluation-set lab. No new generic trial runner is introduced.
- `diagnose.py`: strict response parsing, diagnostic composition and CLI.
- `result.json`, `run-output.txt`, `run-metadata.json`: actual local results and
  source/fixture hashes. No commands in the responses are executed.
- `test_diagnostics.py`: 18 tests, including fresh CLI execution without a model.
- `requirements-lock.txt`: standard library only, not an interpreter image lock.

Expected answers and semantic labels are authored inputs. Incorrect reviewed
expectations can still produce incorrect decisions; hashes only prevent unnoticed
revision mixing. This lab does not prove real runtime actions, safety, external
permissions, human agreement or free-text semantic correctness automatically.
