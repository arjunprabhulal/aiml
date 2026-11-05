# Connect retrieval tools through MCP

This lab starts a real MCP SDK stdio server as a child process, initializes an
SDK client session, discovers tools, searches the pinned documentation corpus
and reads an issued source handle. It does not execute a model agent or generate
an answer. The actual source tools and fixture snapshot are copied unchanged
from the preceding retrieval-tool lesson.

## Prepared runtime and commands

Use Python 3.12 or later with the already installed MCP 2.3.0 environment.
`requirements.txt` pins that SDK; `requirements.lock` records its installed
required-dependency closure. No package installation, model, provider request,
asset download or network service is needed. From this lesson directory:

```sh
python run.py --output /tmp/mcp-retrieval-result.json
python -m unittest -v
python render_output.py /tmp/mcp-retrieval-report.html
```

The client and child server deny outbound socket connections. Their transport is
local process stdin/stdout, not HTTP or loopback sockets. To attach an SDK client
manually, launch `python server.py` as its stdio subprocess. Do not run that
server expecting an interactive terminal UI: stdout belongs to MCP protocol
messages. Server lifecycle diagnostics go to stderr.

This installed SDK uses `MCPServer`, the v2 name for the earlier `FastMCP` class.
The lab deliberately uses the SDK's compatibility `ClientSession.initialize`
path. The actual run negotiates protocol `2025-11-25`; it does not demonstrate the
newer discovery-only client path or claim to negotiate the newest protocol.
The server's small asynchronous tool wrappers retain the original synchronous
SQLite core on the same event-loop thread; they are not a scalable database
execution design.

## Tool schemas and source continuity

`search_documentation(query, version, k=2)` accepts one ASCII alphanumeric term
of at most 64 characters, an exact numeric major.minor version of at most 16
characters, and a strict non-boolean integer k from 1 to 10. Extra arguments are
rejected. Its structured output contains bounded source metadata handles, not
passage text. Each handle records the pinned corpus, issued search request,
source/version/revision, exact line span, raw-source and text hashes, text byte
count, native rank/score and read receipt.

`read_documentation(handle)` accepts the strict handle schema. The running
server must have issued an exactly matching search receipt. It returns the
unchanged source read payload, including text, URL, read request ID and result
hash. Unknown, stale, changed and unissued handles fail. A fresh child server
cannot read a handle until it has issued the matching search itself. These
public hashes and receipt matches are not an authentication or authorization
system; the same deterministic search can issue the same handle again.

One source registry lives for the stdio process and preserves receipts between
search and read calls. It closes during server shutdown. It retains distinct
search receipts for that process's lifetime; there is no global request-rate,
receipt-count or service-memory limit. This is a trusted local demonstration,
not a multi-user service. No HTTP authentication, tenant isolation, credential
management or cross-service production-security claim is made.

The SDK-generated per-tool argument models enforce strict types and forbid
extra fields, and the same schemas appear in `tools/list`. Pydantic output
models describe the exact search/read transport projections. Before returning,
the server checks original authoritative receipts and read payloads. The client
checks structured/text JSON agreement, its original search arguments and pinned
corpus, search/handle receipt hashes, and the read's original handle, exact text
hash, byte count and result hash. These are local structural/source checks,
not a judgment that a passage answers a question.

## Actual protocol and failure record

`runs/2026-10-23-mcp/result.json` contains the actual SDK initialization,
discovered schemas, calls, source results and protocol transcript. The transcript
serializes the original SDK stream messages forwarded between the real client
and server; it is not a packet capture or a handcrafted wireframe. Exact client
stdout/stderr, actual tests, server diagnostics and source/SDK hashes accompany
the record. Temporary paths in the deliberate changed-snapshot startup failure
can differ between runs.

The recorded calls cover successful search/read, no lexical match, absent
version, exact version 3.13, invalid arguments, extra fields and unissued/stale/
changed handles. The installed SDK reports those tool failures with `isError`
true. Its unknown-tool case also returns an error tool result in this run;
that observation is not a claim that every SDK version uses the same error
classification. An empty successful search has `isError` false and no results.
A changed pinned snapshot prevents initialization of a temporary server copy;
it is a startup failure rather than an `isError` tool result.

Tests launch actual child servers and check initialization, discovery, schemas,
receipt continuity and refusal, strict arguments, exact version handling, client
output binding, unchanged-source requirements and clean registry shutdown.
No generated answers or model outcome measurements are included.

## References

- [Official Python SDK v2 overview](https://github.com/modelcontextprotocol/python-sdk)
- [Official SDK migration guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md)
- [MCP tool schemas, results and errors](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

Checked against installed MCP 2.3.0 source and actual execution. The online SDK
links describe its v2 line; the execution record and dependency lock preserve
the exact installed version used here.
