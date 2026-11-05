# A portable model adapter with contract tests

Python 3.11 or later, standard library only. The tests run offline from recorded traffic.
Recording and the command-line example need a local [Ollama](https://ollama.com/download)
server with `gemma4:e2b` and `qwen3.5:0.8b` installed.

```sh
python3 -m unittest -v test_contract.py                              # offline contract tests
python3 adapters.py --api ollama-native "What does JSON stand for?"
python3 adapters.py --api openai-compatible "What does JSON stand for?"
python3 record_wire.py record                                        # live: writes wire-record.json
python3 record_wire.py                                               # offline: writes contract-report.json
```

`adapters.py` defines the contract the application uses: `ChatRequest`, `ChatResult`, and
`AdapterError` with six kinds (`connection`, `timeout`, `model_not_found`, `http`,
`protocol`, `unsupported`). `OllamaChatAdapter` speaks Ollama's native `/api/chat`;
`OpenAICompatibleAdapter` speaks `/v1/chat/completions`, which Ollama also serves. Both turn
thinking off in their own field names, and the OpenAI-compatible adapter refuses a context size
because that API cannot set one.

`test_contract.py` runs the same test methods once per adapter, against responses recorded from
both endpoints with both models, plus edited copies of those responses for failures that are hard
to produce on demand.

## Files

- `adapters.py`: the contract, both adapters and a small command-line example.
- `record_wire.py`: records four cases per model and adapter, and builds the offline report.
- `wire-record.json`: every request body, HTTP status and response body from the recorded run.
- `contract-report.json`: the normalized outcome of each recorded case, and whether the two adapters agree.
- `cli-run.txt`: the command-line example run against both endpoints and two failures.
- `test_contract.py`, `test-output.txt`: offline tests and their recorded output.

## Limits

The adapters cover non-streaming text chat only: no tools, images, structured output or
streaming. They were tested against one server, Ollama 0.32.14, on its two endpoints. Another
server that speaks the OpenAI-compatible format, or a hosted API, needs its own recorded traffic
and must pass the same tests before it counts as supported. The adapters never retry.

## Data and license

The prompts and recorded traffic are synthetic and were written for this lesson; they contain no
third-party data. No model weights are included. Both models are released under the Apache
License 2.0 according to their model cards:
[Gemma 4 E2B IT](https://huggingface.co/google/gemma-4-E2B-it) and
[Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B).
