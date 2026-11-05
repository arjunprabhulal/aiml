<img src="../../../assets/icons/mcp.svg" width="20" height="20" alt=""> [Model Context Protocol (MCP)](../) · lesson 4 of 7

# Expose resources and prompts from an MCP server

[![Expose resources and prompts from an MCP server](lesson.png)](https://aiml.sh/courses/mcp/build-an-mcp-server-with-tools-resources-and-prompts/)

Build a docs server with the MCP Python SDK that offers a search tool, pages as resources and a review prompt, and returns the specified error codes.

- **Full lesson:** [https://aiml.sh/courses/mcp/build-an-mcp-server-with-tools-resources-and-prompts/](https://aiml.sh/courses/mcp/build-an-mcp-server-with-tools-resources-and-prompts/)
- **Reading time:** 20 min
- **Uses:** mcp 2.3.0, the official MCP Python SDK; jsonschema, installed with it, for one test

## Lab

The [`lab/`](lab/) folder holds the complete runnable code, tests and recorded outputs, the same files as the lesson's download on aiml.sh. The lesson explains each step.

### Lab notes

#### Expose resources and prompts from an MCP server

Download `/labs/build-an-mcp-server-with-tools-resources-and-prompts.zip`, extract it, and open `mcp-server-primitives/`. Keep all included source, fixtures, locks and tests together. Requires Python 3.12 or later.

##### Setup and execution

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
