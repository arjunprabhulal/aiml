"""Real MCP SDK stdio server; stdout is reserved for SDK protocol messages."""
from contextlib import asynccontextmanager
import logging
from typing import Annotated
from pydantic import ConfigDict,Field
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from schemas import Handle,Query,Version,SearchResult,ReadResult
from tools import DocumentationTools,ToolError,load_snapshot
from version_documents import canonical_hash


def strict_tool(function):
    tool=Tool.from_function(function,structured_output=True)
    # Per-tool generated argument model: publish and enforce the same strict schema.
    tool.fn_metadata.arg_model.model_config=ConfigDict(extra='forbid',strict=True)
    tool.fn_metadata.arg_model.model_rebuild(force=True)
    tool.parameters=tool.fn_metadata.arg_model.model_json_schema()
    return tool


def build_server():
    registry=DocumentationTools(load_snapshot())

    async def search_documentation(query:Query,version:Version,k:Annotated[int,Field(ge=1,le=10,strict=True)]=2)->SearchResult:
        """Search the pinned corpus by one literal term and exact API version; return read handles."""
        try:
            result=registry.search(query=query,version=version,k=k)
            expected=registry.receipts[result['search_request_id']]
            if canonical_hash(result)!=canonical_hash(expected):raise ToolError('invalid_search_result')
            for handle in result['results']:registry.validate_handle(handle)
            return SearchResult.model_validate(result)
        except (ToolError,ValueError) as error:raise MCPToolError(str(error)) from error

    async def read_documentation(handle:Handle)->ReadResult:
        """Read an exact handle issued by this running server; no arbitrary file or URL access."""
        try:
            receipt=handle.model_dump()
            result=registry.read(receipt)
            registry.validate_read(result,receipt)
            return ReadResult.model_validate(result)
        except (ToolError,ValueError) as error:raise MCPToolError(str(error)) from error

    @asynccontextmanager
    async def lifespan(server):
        logging.info('retrieval registry ready')
        try:yield registry
        finally:
            registry.close()
            logging.info('retrieval registry closed')

    return MCPServer('local-documentation-retrieval',version='1.0.0',tools=[strict_tool(search_documentation),strict_tool(read_documentation)],lifespan=lifespan,log_level='WARNING')


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    build_server().run(transport='stdio')
