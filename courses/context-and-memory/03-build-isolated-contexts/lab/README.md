# Isolated contexts for users, tasks and agents

Python 3.11 or later. Standard library only. In memory. The tests call no model: they grade recorded answers. Recording new answers needs a local Ollama server with `gemma4:e2b`.

## Run

```sh
python demo.py
python answer_check.py                     # grades the recorded answers
python -m unittest -v test_isolation.py test_answer_check.py
```

To record new answers: `ollama pull gemma4:e2b`, then `python answer_check.py record`.

`demo.py` replays `scenario.json`: two users, three tasks, a planner agent and a researcher agent. For each query it records the items the scoped store returns, the items a naive global list returns, and both requests rendered the same way. The output is recorded in `isolation-result.json`; the first test checks that a fresh run still matches it.

## What it does

Every item has one scope:

| Scope | Visible to |
| --- | --- |
| `app` | Everyone. Comes from configuration, never from a principal. |
| `user` | The same user, in any task. |
| `task` | The same user in the same task. |
| `agent` | The same user, task and agent. |

A `Principal` is `(user, task, agent)`. `ContextStore.write` takes the scope keys from the principal, so a caller cannot write into another user's scope by putting a user ID in the text or the payload. Each agent also declares which scopes it reads and which tools it gets.

`handoff` copies a brief and chosen items into the receiving agent's scope in the same task. The sender needs the `delegate` tool and must be able to read each item. Every copy is validated before any is written, so a failed handoff changes nothing. Items are named `handoff-<n>-brief` and `handoff-<n>-item-<k>`, numbered per user. `write` rejects caller IDs that start with `handoff-`, so a written item cannot block a later handoff. An unknown agent raises `ScopeError`. The receiver sees the handoff and nothing else from the sender.

The store enforces only the `delegate` rule. The application that executes tool calls must refuse tools that are not in the agent's list.

`close_task` deletes every task and agent item of that task. `ContextCache` keys a built context by user, task, agent, question and store version.

`naive_context` is the baseline: one global list ranked by shared words with the question.

## Limits

This module enforces scope rules for the principal it receives. It does not authenticate users. Your application must establish who the user is before it builds a `Principal`. Scopes are not document permissions: a user-scoped item can still contain data the user should not see, if it was written there.

`answer_check.py` sends Bob's and Alice's scoped and naive requests to `gemma4:e2b`, pinned by digest in `answer-model.json`, five seeds each, and grades whether the answer carries the other user's data. Twenty answers from a small model illustrate the risk; they are not a measure of answer quality, and the grader uses string rules.

The store is in memory and single-process. A persistent store needs the same scope keys in every query, tests for deletion and cache invalidation, and access checks before data reaches context.

## Files

- `isolation.py`: scopes, store, handoff, cache and baseline.
- `scenario.json`, `demo.py`, `isolation-result.json`: fixture and recorded output.
- `answer_model.py`, `answer-model.json`, `answer_check.py`, `answer-result.json`, `answer-grades.json`: the pinned answer model, recorded answers and grades.
- `test_isolation.py`, `test_answer_check.py`: tests.
