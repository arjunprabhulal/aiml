# 50-turn memory-compaction benchmark

Python 3.11 or later. Token counts come from the pinned Gemma 4 E2B tokenizer and chat template, the same files and hashes as the context budget build; `prepare.py` downloads the tokenizer files once, with no account and no model weights. The tests call no model: they grade recorded answers. Recording new answers needs a local Ollama server with `gemma4:e2b`.

## Run

```sh
python -m pip install -r requirements.txt
python prepare.py                  # once: the pinned tokenizer files
python generate_conversation.py
python benchmark.py                # recorded in benchmark-result.json
python answer_check.py             # grades the recorded answers, recorded in answer-grades.json
python -m unittest -v test_benchmark.py test_answer_check.py
```

To record new answers: `ollama pull gemma4:e2b`, then `python answer_check.py record`.

`generate_conversation.py` writes `conversation.json`: 50 turns of one conversation with labeled memory events, five checkpoints and a token budget. `benchmark.py` replays the conversation and, at each checkpoint, builds the request with four strategies. It records which required facts reach the request, which replaced facts and which forgotten facts leak in, and how many tokens each request uses. Its output is recorded in `benchmark-result.json`; the first test checks that a fresh run still matches it.

## Strategies

- `recent`: newest complete turns only.
- `notes`: recent turns plus cue-word notes from removed turns (the context compaction build's extractor).
- `append-only`: recent turns plus every labeled fact, stored once and never changed or deleted.
- `managed`: recent turns plus labeled facts that are corrected, forgotten and consolidated with the version 4 store from the consolidation build.

Both memory strategies show current facts newest first within a facts quota (160 tokens by default) and fill the rest of the budget with recent turns. The report includes a quota sweep at 120, 160 and 240 tokens.

`answer_check.py` sends the turn-40 and turn-50 requests of every strategy to `gemma4:e2b`, pinned by digest in `answer-model.json`, five seeds each, with the conversation's 512-token context and 128-token answer limit. It grades each answer pass, fail or incomplete. Forty answers from a small model illustrate how these requests behave; they are not a measure of answer quality.

## Limits

The memory strategies use the conversation's labels, so they show what perfect extraction would achieve. A real extractor decides wrongly some of the time, and the benchmark does not measure that. The conversation is synthetic and one user long; the cue-word extractor finds none of its facts because they are phrased as preferences and plans. The benchmark grader checks exact text in the request; the answer grader uses string rules, not a judgment of meaning. The counter is pinned to Gemma 4 E2B; for another model, count with its tokenizer and chat template. The benchmark is deterministic, so one run is enough; the answers were recorded once.

## Files

- `generate_conversation.py`, `conversation.json`: the fixture and its generator.
- `benchmark.py`: strategies, replay and grader.
- `memory.py`, `consolidate.py`: the version 4 store and consolidation, as in the consolidation build.
- `tokenizer.py`, `tokenizer-manifest.json`, `prepare.py`, `requirements.txt`, `requirements.lock`: the pinned tokenizer.
- `benchmark-result.json`: recorded output.
- `answer_model.py`, `answer-model.json`, `answer_check.py`, `answer-result.json`, `answer-grades.json`: the pinned answer model, recorded answers and grades.
- `test_benchmark.py`, `test_answer_check.py`: tests.
