# Route a workflow with conditional edges

Use Python 3.12 or later. Keep the files together and run commands from `adk-graph-routes-lesson/`.

## Set up

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

Export `GOOGLE_API_KEY` privately in this terminal. `.env.example` is an export
reference; the Python client does not load it. Then select the Gemini API:

```bash
unset GOOGLE_GENAI_USE_VERTEXAI DOCS_MODEL
export GOOGLE_GENAI_USE_ENTERPRISE=0
```

## Run the activity

```bash
python graph_client.py --input build-clean.log
python graph_client.py --input build-incomplete.log
python graph_client.py --input build-broken.log
```

Compare the route and event paths for each log. Clean and incomplete logs need
no model call. Only the broken-links branch asks for suggestions. `(ok)` checks
page membership in `docs-pages.txt`; check anchors and meaning yourself.

Model-backed activity uses your provider account. The model configuration limits
each response to 1,024 output tokens.

## Check offline

```bash
python -m unittest -v test_build_router.py test_client.py
```

These checks exercise the actual code with saved replies or explicit fakes. They
make no provider requests. Saved replies illustrate the mechanism; use new cases
and inspect actual answers to evaluate a changed prompt.
