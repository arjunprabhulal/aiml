# Search internal engineering documents with ADK

VertexAiSearchTool adds retrieval settings to a Gemini request. TeamSearch requires one of the fixture teams (docs or platform) and rejects the compatibility mode that discards its dynamic filter. A search filter is an application control; this demo has no sign-in or document ACL integration.

## Run

Use Python 3.12+, Application Default Credentials and an explicitly chosen project where you may create the lesson data store. Indexing, storage and model requests can incur charges.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
python datastore.py create
python datastore.py status
DOCS_TEAM=platform python agent.py "How do I rotate the release signing key?"
```

Wait for the documents to be indexed before querying. record.py makes model requests and writes recordings; it is not an offline test.

## Offline tests

```sh
python -m unittest -v test_agent.py
```

Tests replace model calls with the 2026-10-25 recorded turns. Every recorded request uses TeamSearch with an explicit team, including the query sent before indexing completed. The live run used a unique store with the bundled docuctl documents; that store was deleted after the queries. Set DOCS_SEARCH_STORE to choose a separate exercise-owned store ID.

## Cleanup

Confirm the selected project and lesson store ID, then remove that store and its indexed documents:

```sh
python datastore.py delete
```
