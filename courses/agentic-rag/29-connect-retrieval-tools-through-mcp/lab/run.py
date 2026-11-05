"""Execute actual SDK initialize/list/search/read over child-process stdio."""
import argparse
import asyncio
import copy
import json
import shutil
import tempfile
from pathlib import Path
from client import session,validated_result
from tools import load_snapshot


def dump(result):return result.model_dump(mode='json',by_alias=True,exclude_none=True)


async def run():
    calls=[]
    async with session() as state:
        client=state['client'];initialized=await client.initialize();listed=await client.list_tools()
        async def call(case_id,name,arguments):
            result=await client.call_tool(name,arguments)
            calls.append({'case_id':case_id,'tool':name,'arguments':copy.deepcopy(arguments),'result':dump(result)})
            return result
        search_arguments={'query':'text','version':'3.12','k':2}
        search=validated_result(await call('search','search_documentation',search_arguments),'search',expected_search=search_arguments,expected_corpus_id=load_snapshot()['snapshot_id'])
        handle=search['results'][0]
        read=validated_result(await call('read-issued-handle','read_documentation',{'handle':handle}),'read',handle)
        await call('empty-search','search_documentation',{'query':'zzunmatched','version':'3.12','k':2})
        await call('absent-version','search_documentation',{'query':'text','version':'9.99','k':2})
        await call('version-3-13','search_documentation',{'query':'read','version':'3.13','k':2})
        await call('invalid-arguments','search_documentation',{'query':'text','version':'3.12','k':True})
        await call('extra-argument','search_documentation',{'query':'text','version':'3.12','unexpected':1})
        for name,key,value in [('unissued-receipt','search_request_id','0'*64),('stale-corpus','corpus_id','0'*64),('changed-handle','byte_count',handle['byte_count']+1)]:
            changed={**handle,key:value}
            await call(name,'read_documentation',{'handle':changed})
        protocol_error=None
        try:
            result=await client.call_tool('unknown_documentation_tool',{})
            protocol_error={'kind':'tool_result','result':dump(result)}
        except Exception as error:protocol_error={'kind':'exception','type':type(error).__name__,'message':str(error)}
    # A new child process has no issued receipt, even with the same source snapshot.
    async with session() as other:
        await other['client'].initialize()
        foreign=await other['client'].call_tool('read_documentation',{'handle':handle})
    startup_diagnostics={}
    startup_failure={'status':'unexpectedly_initialized'}
    with tempfile.TemporaryDirectory() as temporary:
        copied=Path(temporary)/'changed-server'
        shutil.copytree(Path(__file__).parent,copied,ignore=shutil.ignore_patterns('__pycache__','runs'))
        snapshot=copied/'fixtures/snapshot.json'
        snapshot.write_text(snapshot.read_text()+' ')
        try:
            async with session(copied/'server.py',startup_diagnostics) as broken:
                await broken['client'].initialize()
        except Exception as error:
            startup_failure={'status':'failed_before_initialize','exception_type':type(error).__name__,'server_stderr':startup_diagnostics['server_stderr'],'protocol_frames':startup_diagnostics['frames']}
    return {'changed_snapshot_startup':startup_failure,'execution_mode':'actual-mcp-sdk-stdio-client-server','model_called':False,'sdk_entrypoints':['MCPServer','stdio_client','ClientSession.initialize','ClientSession.list_tools','ClientSession.call_tool'],'initialization':dump(initialized),'tools':dump(listed),'calls':calls,'validated_search':search,'validated_read':read,'unknown_tool':protocol_error,'fresh_process_read':dump(foreign),'protocol_transcript':state['frames'],'server_stderr':state['server_stderr'],'fresh_process_stderr':other['server_stderr'],'limit':'Actual local SDK transport and source-binding checks only. ClientSession uses the SDK legacy-handshake compatibility path. No model agent, generation, HTTP authentication, cross-service authorization or production-security claim.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result=asyncio.run(run());args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'execution_mode':result['execution_mode'],'protocol_version':result['initialization']['protocolVersion'],'tools':[t['name'] for t in result['tools']['tools']],'read_source':result['validated_read']['source_id'],'recorded_calls':len(result['calls']),'model_called':False},sort_keys=True))
