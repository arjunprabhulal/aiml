# Add human-in-the-loop interrupts

Lab for https://aiml.sh/courses/langgraph/add-human-in-the-loop-interrupts/. Use Python 3.12 or later.

## Setup

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
```

## Run and test

Live model commands require `GOOGLE_API_KEY`; `REVIEW_MODEL=gemma4:e2b` selects an already available local Ollama model. The test command uses fakes and saved replies, without a model call.

```sh
python3 -m pip install -r requirements-lock.txt
python3 record.py
```

```sh
python3 -m pytest -v test_graph.py
```

`run-output.txt` and `runs.json` contain saved model runs; `test-output.txt` is a separate saved test result. A graph finishing does not establish that its answer or side effect is correct. The lesson explains the supplied failure cases and fixture limits.
