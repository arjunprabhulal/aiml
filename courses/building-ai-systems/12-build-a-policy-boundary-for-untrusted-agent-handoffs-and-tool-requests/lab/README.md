# Docuctl proposal policy

Python 3.11 or newer; the current Docuctl demonstration uses only the standard library and makes no model requests. Unzip the complete lab and run commands from this directory.

```bash
python3 -m venv .venv
source .venv/bin/activate
python docuctl_demo.py
python -m unittest -v test_docuctl.py
```

`docuctl-output.json` is the saved output of this local demonstration. Its proposals are authored test inputs, not recorded model choices. Publication and review are simulated local decisions; the demonstration does not publish documentation or contact another service.

## Preserved historical experiment

The original source files, test fixtures and model recordings below retain their original identifiers. The Docuctl demonstration does not rename or regenerate those records. Commands that explicitly record new model output are optional historical instructions and are not required for the current lesson.

# A policy boundary for untrusted retrieval, tool outputs and agent handoffs

Python 3.11 or newer, standard library only. Tested with Python 3.11 and 3.15. Recording new replies needs a local Ollama server with `gemma4:e2b` at the digest in `model.json`; replaying them needs nothing else.

- `policy.py`: the boundary. It refuses unknown tools and arguments that are not exactly the tool's parameters, refuses an order ID or an email address that is not the signed-in customer's own, refuses a refund reason outside its list, holds a refund for review once untrusted text is in the conversation, and checks a handoff's fields before the model sees it.
- `run_policy.py`: the agent loop. The model proposes calls, the boundary decides, allowed calls run against simulated tools, and every result, refusal or hold goes back to the model. Live through Ollama, or replayed from `recorded/replies.json`, keyed by the SHA-256 of each exact request.
- `world.json`: the account, the notes (one with an injected instruction), a handoff with an injected instruction, and four scenarios. `model.json`: the pinned model and the five seeds.
- `decisions.json`: every proposed call and decision for each scenario and seed.
- `test_policy.py`: `python3 -m unittest -v test_policy.py`

```bash
python3 run_policy.py record   # live: Ollama with the pinned model; rewrites recorded/replies.json
python3 run_policy.py          # offline: rewrites decisions.json
python3 run_policy.py --check  # offline: compares a fresh replay with decisions.json byte for byte
```

`recorded/replies.json` keeps each reply's text and tool calls only, not Ollama's timing fields such as `total_duration`, so the build reports no latency. The replies were recorded on macOS on Apple silicon (arm64). The scenarios in `world.json` are development cases written with the build; there is no held-out set.

All accounts, notes and handoffs are synthetic, written for this build on October 20, 2026; the injected sentences are part of the test data. The model is [Gemma 4 E2B](https://huggingface.co/google/gemma-4-E2B-it), Apache-2.0, run through Ollama 0.32.14.
