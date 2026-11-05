<img src="../../../assets/icons/google-adk.png" width="20" height="20" alt=""> [Building Agents with Google ADK 2.0](../) · lesson 16 of 17

# Run independent workflow branches and gather results

[![Run independent workflow branches and gather results](lesson.png)](https://aiml.sh/courses/google-adk/parallel-fan-out-and-gather/)

Run ADK 2.0 workflow branches in parallel and merge them with a JoinNode, then see one failed branch fail the graph and a dynamic parent keep the rest.

- **Full lesson:** [https://aiml.sh/courses/google-adk/parallel-fan-out-and-gather/](https://aiml.sh/courses/google-adk/parallel-fan-out-and-gather/)
- **Reading time:** 25 min
- **Uses:** google-adk 2.12.0 with google-genai 2.32.0

## Lab

The [`lab/`](lab/) folder holds the complete runnable code, tests and recorded outputs, the same files as the lesson's download on aiml.sh. The lesson explains each step.

### Lab notes

#### Parallel fan out and gather

This flat project contains the workflow, input fixtures, saved model replies and offline tests. Use Python 3.12+.

##### Set up

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

##### Compare the cases

```sh
python run.py
```

The default runs the real ADK workflow with saved model replies. It makes no model request and does not overwrite the fixtures. Inspect each case's routes, final message or expected error. It checks behavior for the saved replies, not general answer quality.

To request new Gemini replies instead, copy `.env.example` to `.env`, set your API key and run `python run.py --live`. Existing shell variables take precedence. Clear alternate backend settings from previous activities if necessary. Model wording and outcomes can differ. The agents use LOW thinking and a 1,024-token output cap per request; truncation can leave structured output incomplete.

##### Offline checks

```sh
python -W ignore -m unittest -v test_release_prep.py test_runner.py
```

The suite replays fixtures and uses controlled models to check the pattern's failure boundaries. `test_runner.py` exercises the comparison entry point through the actual workflows.

##### Recorded execution evidence

The recorder made real Gemini API calls and used the local tools and services in this lab. The [provider attempt metadata and output hashes](lab/runs/docuctl-2026-10-25/provenance.json) identify the recorded output and captured attempts. Raw provider receipts remain private; the download excludes opaque model signatures and SQLite binaries. These records do not demonstrate browser interaction or reliability across other questions. Run the offline tests to exercise the selected replies without making paid model calls.
