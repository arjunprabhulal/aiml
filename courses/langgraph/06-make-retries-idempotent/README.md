<img src="../../../assets/icons/langgraph.png" width="20" height="20" alt=""> [Building Agents with LangGraph](../) · lesson 6 of 9

# Make LangGraph retries idempotent

[![Make LangGraph retries idempotent](lesson.png)](https://aiml.sh/courses/langgraph/make-retries-idempotent/)

Retry a ticket-filing write with a LangGraph RetryPolicy, see a retry file a duplicate, and stop duplicates across retries and resumes with an idempotency key.

- **Full lesson:** [https://aiml.sh/courses/langgraph/make-retries-idempotent/](https://aiml.sh/courses/langgraph/make-retries-idempotent/)
- **Reading time:** 22 min
- **Uses:** langgraph 1.2.16, langchain-core 1.6.12, langchain-google-genai 4.4.2, pydantic 2.14.1; langchain-ollama 1.1.0 for the local alternative; pytest 9.1.1 for the offline tests

## Lab

The [`lab/`](lab/) folder holds the complete runnable code, tests and recorded outputs, the same files as the lesson's download on aiml.sh. The lesson explains each step.

### Lab notes

#### Make LangGraph retries idempotent

Lab for https://aiml.sh/courses/langgraph/make-retries-idempotent/. Use Python 3.12 or later.

##### Setup

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
```

##### Run and test

Live model commands require `GOOGLE_API_KEY`; `REVIEW_MODEL=gemma4:e2b` selects an already available local Ollama model. The test command uses fakes and saved replies, without a model call.

```sh
python record.py
```

```sh
python -m pytest -v test_workflow.py
```

`run-output.txt` and `runs.json` contain saved model runs; `test-output.txt` is a separate saved test result. A graph finishing does not establish that its answer or side effect is correct. The lesson explains the supplied failure cases and fixture limits.
