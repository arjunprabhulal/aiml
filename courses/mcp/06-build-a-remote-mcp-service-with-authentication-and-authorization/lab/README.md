# Secure a remote MCP server with OAuth 2.1 and scoped tokens

Download `/labs/build-a-remote-mcp-service-with-authentication-and-authorization.zip`, extract it, and open `mcp-remote-auth/`. Keep all included source, fixtures, locks and tests together. Requires Python 3.12 or later.

## Setup and execution

The local tests use the real SDK and server. They do not call a hosted model.

From this lab directory, follow the commands in order. Separate terminal comments mark servers that must keep running. Read each script before invoking it. Recording drivers can replace the bundled result files, so use a fresh extracted copy for new runs.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
```

```sh
.venv/bin/python record_flows.py --write auth-flows.json
```

```sh
.venv/bin/python -m unittest -v test_remote_auth.py
```

Saved output files describe the original runs. Passing the offline/local tests checks the stated contracts; it does not establish model quality or production security.
