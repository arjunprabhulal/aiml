# Build a coding-agent loop

This original teaching lab sends a coding task to an already installed local Ollama model. The Python harness collects streamed assistant messages, executes three repository tools and sends their results into the next model request. A separate pytest run checks the resulting repository.

Use only the supplied disposable sample repository. This harness is not a sandbox. The model can edit Python that the test subprocess executes with your user's permissions. The tool list is narrow and the child process does not inherit API keys, but those choices do not provide process, filesystem or network isolation. Do not point this pilot at an untrusted project.

## Run

Python 3.11 or later, Ollama and a tool-capable model are required. The recorded model is `gemma4:e2b`; its exact digest is saved in each run record. The weights are not included here. If that model is not already installed, check its download size and license before fetching it.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/python record_run.py
.venv/bin/python -m pytest -q test_loop.py test_recorded.py
```

`record_run.py` copies `sample_repo/` to a temporary directory. It records failing tests, calls the model, runs the resulting tests independently and saves the model chunks, tool calls, test outcomes and changed source. It leaves the starting sample unchanged. Low temperature and a seed do not make future model output identical.

To inspect a bounded incomplete attempt, use `--max-turns 1 --output recorded-max-turns.json`. A turn is one model response stream, not one tool call or one text fragment. A final assistant message is a stop condition, not a passing test result.

Offline tests replay saved model responses through the actual tools and sample tests. They do not call Ollama or predict another live response. The sample's tests cover the supplied path examples; passing them does not establish behavior for every possible repository path.

## Files

- `harness/loop.py`: messages, streamed response assembly, tool dispatch and stop events.
- `harness/ollama_model.py`: the actual Ollama SDK adapter.
- `harness/tools.py`: fixed file reads, one exact text replacement and a fixed pytest command.
- `sample_repo/`: the deliberately faulty CI path filter and its tests.
- `record_run.py`: one local recording and the independent outcome check.
- `test_loop.py`, `test_recorded.py`: offline loop, tool and recorded-task checks.

The loop intentionally remains handwritten because it is the subject of this lesson. Google ADK's Runner and LangGraph's model/tool cycle manage this orchestration in applications that do not need to implement a harness themselves. Sessions, sandboxing, general shell execution, context compaction, MCP and parallel tool execution are not implemented here.

## Licenses and sources

The original lab source and sample files use MIT; see LICENSE. Ollama's Python SDK and pytest are MIT. The existing Gemma 4 E2B model is Apache 2.0, according to Google's model card and license; no model weights are redistributed.

Official references checked October 22, 2026:

- https://docs.ollama.com/capabilities/tool-calling
- https://docs.ollama.com/api/chat
- https://github.com/ollama/ollama-python
- https://huggingface.co/google/gemma-4-E2B-it
- https://ai.google.dev/gemma/apache_2
- https://code.claude.com/docs/en/how-claude-code-works
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/hooks
- https://developers.openai.com/codex/cli
- https://geminicli.com/docs/core/
- https://geminicli.com/docs/hooks/
- https://modelcontextprotocol.io/specification/2025-11-25/server/tools

These products are architectural references. This lab does not copy their implementation, provide their features or integrate their protocols.
