# Build an MCP client with discovery, calls and tracing

Download `/labs/build-an-mcp-client.zip`, extract it, and open `mcp-client-tracing/`. Keep all included source, fixtures, locks and tests together. Requires Python 3.12 or later.

## Setup and execution

The local tests use the real SDK and server. They do not call a hosted model.

From this lab directory, follow the commands in order. Separate terminal comments mark servers that must keep running. Read each script before invoking it. Recording drivers can replace the bundled result files, so use a fresh extracted copy for new runs.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
```

```sh
.venv/bin/python traced_client.py --write-log execution-log.json --write-trace trace-tree.json
```

```sh
.venv/bin/python -m unittest -v test_traced_client.py
```

Saved output files describe the original runs. Passing the offline/local tests checks the stated contracts; it does not establish model quality or production security.
