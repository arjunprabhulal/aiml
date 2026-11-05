# Expose resources and prompts from an MCP server

Download `/labs/build-an-mcp-server-with-tools-resources-and-prompts.zip`, extract it, and open `mcp-server-primitives/`. Keep all included source, fixtures, locks and tests together. Requires Python 3.12 or later.

## Setup and execution

The local tests use the real SDK and server. They do not call a hosted model.

From this lab directory, follow the commands in order. Separate terminal comments mark servers that must keep running. Read each script before invoking it. Recording drivers can replace the bundled result files, so use a fresh extracted copy for new runs.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
```

```sh
.venv/bin/python inspect_server.py --write primitives-results.json
```

```sh
.venv/bin/python -m unittest -v test_docs_server.py
```

Saved output files describe the original runs. Passing the offline/local tests checks the stated contracts; it does not establish model quality or production security.
