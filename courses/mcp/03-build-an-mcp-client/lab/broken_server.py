"""A deliberately broken MCP server for one client test. Standard library only.

It speaks protocol 2026-07-28 over stdio, offers only tools, and returns
structuredContent that breaks its own outputSchema: "text" is missing.
"""
import json
import sys

META = {"io.modelcontextprotocol/serverInfo": {"name": "broken-docs", "version": "1.0.0"}}
TOOL = {"name": "search_docs", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        "outputSchema": {"type": "object", "properties": {"slug": {"type": "string"}, "text": {"type": "string"}},
                         "required": ["slug", "text"]}}
RESULTS = {
    "server/discover": {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}, "ttlMs": 0, "cacheScope": "public"},
    "tools/list": {"tools": [TOOL], "ttlMs": 0, "cacheScope": "public"},
    "tools/call": {"content": [{"type": "text", "text": "{\"slug\": \"retries\"}"}], "structuredContent": {"slug": "retries"}},
}

for line in sys.stdin:
    message = json.loads(line)
    if "id" in message:
        reply = {"jsonrpc": "2.0", "id": message["id"]}
        if message["method"] in RESULTS:
            reply["result"] = {"resultType": "complete", **RESULTS[message["method"]], "_meta": META}
        else:
            reply["error"] = {"code": -32601, "message": "Method not found"}
        print(json.dumps(reply), flush=True)
