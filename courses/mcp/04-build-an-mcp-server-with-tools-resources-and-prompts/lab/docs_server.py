"""A docs server: one search tool, the docs pages as resources and a review prompt.

Run over stdio with `python docs_server.py`. The pages come from docs.json.
Built with the official MCP Python SDK (mcp 2.3.0).
"""
import json
from pathlib import Path
from typing import TypedDict

from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp.server.mcpserver.prompts.base import UserMessage
from mcp.types import INVALID_PARAMS, EmbeddedResource, TextResourceContents, ToolAnnotations

PAGES = json.loads((Path(__file__).with_name("docs.json")).read_text(encoding="utf-8"))["pages"]


class DocsServer(MCPServer):
    """Report an unknown prompt or a missing prompt argument as -32602, as the prompts specification asks."""

    async def get_prompt(self, name, arguments=None, context=None):
        prompt = next((p for p in await self.list_prompts() if p.name == name), None)
        if prompt is None:
            raise MCPError(INVALID_PARAMS, f"Unknown prompt: {name}")
        missing = [a.name for a in prompt.arguments or [] if a.required and a.name not in (arguments or {})]
        if missing:
            raise MCPError(INVALID_PARAMS, f"Missing required arguments: {', '.join(missing)}")
        return await super().get_prompt(name, arguments, context)


server = DocsServer("docs", version="1.0.0", instructions="Search and read the taskq documentation.")


class SearchHit(TypedDict):
    slug: str
    title: str
    uri: str


@server.tool(title="Search the docs", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def search_docs(query: str) -> list[SearchHit]:
    """Return the docs pages whose text contains every word of the query."""
    words = query.lower().split()
    if not words:
        raise ToolError("The query is empty. Pass one or more words, such as 'worker timeout'.")
    return [{"slug": slug, "title": page["title"], "uri": f"docs://pages/{slug}"}
            for slug, page in PAGES.items() if all(word in page["body"].lower() for word in words)]


@server.resource("docs://index", title="Docs index", mime_type="application/json")
def docs_index() -> str:
    """Every page's slug and title."""
    return json.dumps([{"slug": slug, "title": page["title"]} for slug, page in PAGES.items()])


@server.resource("docs://pages/{slug}", title="Docs page", mime_type="text/markdown")
def docs_page(slug: str) -> str:
    """The Markdown text of one docs page."""
    if slug not in PAGES:
        raise ResourceNotFoundError(f"No docs page named {slug}.")
    return PAGES[slug]["body"]


@server.prompt(title="Review a docs page")
def review_page(slug: str, focus: str = "accuracy") -> list[UserMessage]:
    """Ask the model to review one docs page; the page text is embedded in the prompt."""
    if slug not in PAGES:
        raise MCPError(INVALID_PARAMS, f"No docs page named {slug}.")
    page = TextResourceContents(uri=f"docs://pages/{slug}", mime_type="text/markdown", text=PAGES[slug]["body"])
    return [UserMessage(EmbeddedResource(type="resource", resource=page)),
            UserMessage(f"Review this docs page for {focus}. List each problem with the sentence it is in.")]


if __name__ == "__main__":
    server.run()
