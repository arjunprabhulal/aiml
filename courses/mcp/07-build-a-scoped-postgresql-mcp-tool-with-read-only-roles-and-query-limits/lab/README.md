# Build a read-only database MCP server with scoped roles

Download `/labs/build-a-scoped-postgresql-mcp-tool-with-read-only-roles-and-query-limits.zip`, extract it, and open `mcp-postgres-readonly/`. Keep all included source, fixtures, locks and tests together. Requires Python 3.12 or later.

## Setup and execution

Requires PostgreSQL 17. `PG_BIN` names the directory containing `initdb`, `pg_ctl` and `postgres`; the commands derive it from `pg_config` and print the version for you to check. Both the recording and tests use a disposable real local cluster, not mocks. Never point setup at an existing database. No model is called.

From this lab directory, follow the commands in order. Separate terminal comments mark servers that must keep running. Read each script before invoking it. Recording drivers can replace the bundled result files, so use a fresh extracted copy for new runs.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
export PG_BIN="$(pg_config --bindir)"
"$PG_BIN/postgres" --version
```

```sh
PG_DIR="$(mktemp -d)/cluster"
.venv/bin/python lesson_cluster.py create "$PG_DIR" --port 54329
export DOCS_READER_DSN="$(cat "$PG_DIR/reader.dsn")"
# ... use the server ...
.venv/bin/python lesson_cluster.py destroy "${PG_DIR:?set PG_DIR first}"
```

```sh
.venv/bin/python record_results.py --write query-results.json
```

```sh
.venv/bin/python -m unittest -v test_postgres_readonly.py
```

Saved output files describe the original runs. Passing the offline/local tests checks the stated contracts; it does not establish model quality or production security.
