# Engineering reliable agents — local workshop

Nine connected labs use a fictional docuctl documentation assistant. The baseline,
loop and worker demonstrations use explicitly scripted policies. They exercise
real Python control flow and local tools; they are not model conversations.
The retrieval optimization, SQLite memory and restricted repair processes run
locally. No paid API, model download, cloud deployment or external write is needed.

## Prepare

Use Python 3.12 or later. Extract the complete ZIP and enter agent-engineering.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m unittest discover -p 'test_*.py' -v
```

On PowerShell, activate with .venv\Scripts\Activate.ps1. There are no third-party
Python requirements; requirements-lock.txt records that dependency contract.

## Run the lessons

| Lesson | Command | What to inspect |
| --- | --- | --- |
| Task and workflow baseline | python task_baseline.py | Same cases and tools; the workflow and scripted loop tie. |
| Bounded tool loop | python tool_loop.py | search, read, final; independently checked command and citation. |
| Worker delegation | python delegation.py | Separate worker state and additional dispatch/merge work. |
| Curate development data | python curate_traces.py --save-dir curated | No task family crosses the split; known patterns redacted. |
| Optimize retrieval | python optimize_retrieval.py | Select on development data, then evaluate the frozen policy on test. |
| Graders and repeated trials | python judge_trials.py | False positives and the difference between any and all successes. |
| Restricted terminal harness | python terminal_harness.py | Fresh candidate files, process exits and actual boundary checks. |
| Memory lifecycle | python memory_lifecycle.py | Correction, principal scope, expiry and deletion of all revisions. |
| Independent outcome checks | python benchmark.py | A completion claim can accompany a failing implementation. |

The corresponding *-output.txt files contain actual local demonstration output.
run-metadata.json records the commands, exit codes and hashes of the shared lab
files used to produce those outputs.
The curation command writes train.json, development.json and test.json under
curated/. Each record binds its redacted case to the decisions and tool results
produced by that case. Redaction covers question emails and TOKEN= values only;
it is not a general data-loss-prevention system.
The dataset is deliberately small and synthetic: 18 questions in 9 task families,
with train/development/test split by family. These examples teach the protocol;
they do not measure production retrieval or model reliability.

## Optional installed-model experiment

The loop has a callable policy boundary. provider.py supplies an Ollama JSON-decision
adapter for a model you already have installed. Inspect the official Ollama model
card and its license before selecting it. The author has not executed this adapter
against an installed model; its request bound has an offline test.

```bash
ollama list
export OLLAMA_MODEL='exact-name-from-your-installed-model-list'
python tool_loop.py --provider ollama --case rollback-direct --save my-trace.json
```

It sends at most 4 requests to the fixed loopback /api/chat endpoint, with 30-second
request timeouts and 512 requested output tokens. There are no retries, downloads
or shell/deployment tools. A length stop, invalid JSON, transport error, invented
citation or exhausted budget is an incomplete/failed run. A source citation alone
does not prove that the command answers the question; inspect the task outcome.

## Important boundaries

- task_baseline.py compares a naive keyword route with a fixed search/read workflow
  and the same operations under scripted loop control. The workflow and loop share
  retrieval settings and a two-tool budget; the labels do not imply an LLM win.
- optimize_retrieval.py optimizes passage recall and context count, not prompts or
  model weights. Its glossary comes from the documentation, not test labels.
- judge-cases.json contains authored synthetic reference labels. No human study or
  model judge was run. The four trial Booleans are a calculation fixture.
- terminal_harness.py accepts only one comparison between attempt and max_attempts.
  It is not an OS sandbox for arbitrary generated Python or shell commands.
- memory_lifecycle.py takes a caller-provided principal. An authenticated application
  must supply that identity. Expired rows remain stored until deleted; deletion
  here removes SQLite rows, not copies in backups or external logs.
- The shared lab is complete in each lesson ZIP. Do not combine different workshop
  versions when reproducing the outputs.
