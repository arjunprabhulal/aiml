"""Actual SDK client session over subprocess stdio, with observed protocol frames."""
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import anyio
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.message import SessionMessage
from schemas import SearchResult,ReadResult
from version_documents import canonical_hash

ROOT=Path(__file__).parent


def validated_result(result,kind,expected_handle=None,expected_search=None,expected_corpus_id=None):
    if kind not in ('search','read'):raise ValueError('invalid_result_kind')
    if result.is_error:raise ValueError('tool_execution_error')
    data=result.structured_content
    model=SearchResult if kind=='search' else ReadResult
    validated=model.model_validate(data).model_dump()
    texts=[block.text for block in result.content if block.type=='text']
    if len(texts)!=1 or canonical_hash(json.loads(texts[0]))!=canonical_hash(validated):raise ValueError('structured_text_result_mismatch')
    if kind=='search':
        if expected_search is None or expected_corpus_id is None:raise ValueError('missing_search_binding')
        request={'corpus_id':expected_corpus_id,'query':expected_search['query'].lower(),'version':expected_search['version'],'k':expected_search.get('k',2)}
        if any(validated[key]!=value for key,value in request.items()) or validated['search_request_id']!=canonical_hash(request):raise ValueError('search_request_binding_mismatch')
        seen=set()
        for rank,handle in enumerate(validated['results'],1):
            if handle['corpus_id']!=expected_corpus_id or handle['search_request_id']!=validated['search_request_id'] or handle['version']!=request['version'] or handle['rank']!=rank or handle['passage_id'] in seen:raise ValueError('search_handle_binding_mismatch')
            if handle['read_token']!=canonical_hash({k:v for k,v in handle.items() if k!='read_token'}):raise ValueError('search_handle_token_mismatch')
            seen.add(handle['passage_id'])
    if kind=='read':
        if expected_handle is None or any(validated.get(key)!=value for key,value in expected_handle.items()):raise ValueError('read_handle_binding_mismatch')
        text=validated['text']
        if hashlib.sha256(text.encode('utf-8')).hexdigest()!=validated['text_sha256']:raise ValueError('read_text_hash_mismatch')
        if len(text.encode('utf-8'))!=validated['byte_count']:raise ValueError('read_byte_count_mismatch')
        body={key:value for key,value in validated.items() if key!='result_sha256'}
        if canonical_hash(body)!=validated['result_sha256']:raise ValueError('read_result_hash_mismatch')
    return validated


@asynccontextmanager
async def session(server_path=None,diagnostics=None):
    """Forward actual SDK stream objects, recording their original JSON-RPC data."""
    frames=[];logs=tempfile.TemporaryFile(mode='w+',encoding='utf-8')
    path=server_path or ROOT/'server.py'
    guarded='import socket,runpy; socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError("network_disabled_for_offline_server")); socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(RuntimeError("network_disabled_for_offline_server")); runpy.run_path('+repr(str(path))+',run_name="__main__")'
    parameters=StdioServerParameters(command=sys.executable,args=['-c',guarded],cwd=str(path.parent),env={**os.environ,'PYTHONUNBUFFERED':'1'})
    state={} if diagnostics is None else diagnostics
    state.update({'frames':frames,'server_stderr':''})
    try:
        async with stdio_client(parameters,errlog=logs) as (wire_read,wire_write):
            server_send,client_receive=anyio.create_memory_object_stream(16)
            client_send,server_receive=anyio.create_memory_object_stream(16)
            async def relay(source,destination,direction):
                async with source,destination:
                    async for message in source:
                        if isinstance(message,SessionMessage):
                            frames.append({'direction':direction,'message':message.message.model_dump(mode='json',by_alias=True,exclude_none=True)})
                        else:frames.append({'direction':direction,'stream_error':str(message)})
                        await destination.send(message)
            async with anyio.create_task_group() as group:
                group.start_soon(relay,wire_read,server_send,'server_to_client')
                group.start_soon(relay,server_receive,wire_write,'client_to_server')
                async with ClientSession(client_receive,client_send,read_timeout_seconds=10) as client:
                    state['client']=client
                    yield state
                group.cancel_scope.cancel()
    finally:
        logs.seek(0);state['server_stderr']=logs.read();logs.close()
