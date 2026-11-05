"""Each transport test launches an actual SDK stdio child server."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from client import session,validated_result
from tools import load_snapshot
from version_documents import canonical_hash

ARGS={'query':'text','version':'3.12','k':2}


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_initialize_discovery_search_read_and_clean_shutdown(self):
        async with session() as state:
            client=state['client'];initialized=await client.initialize();listed=await client.list_tools()
            searched=await client.call_tool('search_documentation',ARGS)
            payload=searched.structured_content
            handle=payload['results'][0]
            read=await client.call_tool('read_documentation',{'handle':handle})
        self.assertEqual(initialized.protocol_version,'2025-11-25')
        self.assertEqual({t.name for t in listed.tools},{'search_documentation','read_documentation'})
        self.assertTrue(all(t.input_schema['additionalProperties'] is False for t in listed.tools))
        self.assertTrue(all(t.output_schema is not None for t in listed.tools))
        validated_result(searched,'search',expected_search=ARGS,expected_corpus_id=load_snapshot()['snapshot_id'])
        result=validated_result(read,'read',handle)
        self.assertEqual(result['source_id'],'path-read')
        methods=[f['message'].get('method') for f in state['frames'] if f['direction']=='client_to_server']
        self.assertIn('initialize',methods);self.assertIn('tools/list',methods);self.assertEqual(methods.count('tools/call'),2)
        self.assertTrue(all('message' in f and f['message']['jsonrpc']=='2.0' for f in state['frames']))
        self.assertIn('retrieval registry closed',state['server_stderr'])

    async def test_strict_invalid_arguments_and_extra_fields_are_error_results(self):
        arguments=[{**ARGS,'k':True},{**ARGS,'k':'2'},{**ARGS,'k':11},{**ARGS,'query':'text OR read'},{**ARGS,'version':'1'*17+'.0'},{**ARGS,'extra':1},{'query':'text'}]
        async with session() as state:
            await state['client'].initialize()
            results=[await state['client'].call_tool('search_documentation',a) for a in arguments]
        self.assertTrue(all(r.is_error and r.structured_content is None for r in results))

    async def test_unissued_stale_changed_and_foreign_handles_fail(self):
        async with session() as state:
            await state['client'].initialize()
            searched=await state['client'].call_tool('search_documentation',ARGS);handle=searched.structured_content['results'][0]
            results=[]
            for key,value in [('search_request_id','0'*64),('corpus_id','0'*64),('byte_count',handle['byte_count']+1),('version','3.13')]:
                results.append(await state['client'].call_tool('read_documentation',{'handle':{**handle,key:value}}))
        async with session() as other:
            await other['client'].initialize();foreign=await other['client'].call_tool('read_documentation',{'handle':handle})
        self.assertTrue(all(r.is_error for r in results));self.assertTrue(foreign.is_error)
        self.assertIn('unissued_search_receipt',foreign.content[0].text)

    async def test_empty_and_exact_version_results_do_not_fallback(self):
        async with session() as state:
            await state['client'].initialize()
            empty=await state['client'].call_tool('search_documentation',{'query':'zzunmatched','version':'3.12'})
            absent=await state['client'].call_tool('search_documentation',{'query':'text','version':'9.99'})
            current=await state['client'].call_tool('search_documentation',{'query':'read','version':'3.13'})
        self.assertFalse(empty.is_error);self.assertEqual(empty.structured_content['results'],[])
        self.assertFalse(absent.is_error);self.assertEqual(absent.structured_content['results'],[])
        self.assertTrue(all(h['version']=='3.13' for h in current.structured_content['results']))

    async def test_client_validates_search_request_binding_and_read_integrity(self):
        async with session() as state:
            await state['client'].initialize();searched=await state['client'].call_tool('search_documentation',ARGS)
            handle=searched.structured_content['results'][0];read=await state['client'].call_tool('read_documentation',{'handle':handle})
        with self.assertRaisesRegex(ValueError,'search_request_binding'):validated_result(searched,'search',expected_search={**ARGS,'query':'json'},expected_corpus_id=load_snapshot()['snapshot_id'])
        changed=read.model_copy(deep=True);changed.structured_content['text']='X'+changed.structured_content['text'][1:]
        changed.structured_content['result_sha256']=canonical_hash({k:v for k,v in changed.structured_content.items() if k!='result_sha256'})
        changed.content[0].text=json.dumps(changed.structured_content)
        with self.assertRaisesRegex(ValueError,'read_text_hash'):validated_result(changed,'read',handle)
        changed=read.model_copy(deep=True);changed.content[0].text='{}'
        with self.assertRaisesRegex(ValueError,'structured_text_result'):validated_result(changed,'read',handle)

    async def test_unknown_tool_uses_observed_sdk_is_error_semantics(self):
        async with session() as state:
            await state['client'].initialize();result=await state['client'].call_tool('unknown_documentation_tool',{})
        self.assertTrue(result.is_error);self.assertIn('Unknown tool',result.content[0].text)

    async def test_changed_pinned_snapshot_fails_before_initialization(self):
        diagnostics={};failed=False
        with tempfile.TemporaryDirectory() as temporary:
            copied=Path(temporary)/'server'
            shutil.copytree(Path(__file__).parent,copied,ignore=shutil.ignore_patterns('__pycache__','runs'))
            snapshot=copied/'fixtures/snapshot.json';snapshot.write_text(snapshot.read_text()+' ')
            try:
                async with session(copied/'server.py',diagnostics) as broken:
                    await broken['client'].initialize()
            except Exception:failed=True
        self.assertTrue(failed)
        self.assertIn('snapshot_file_hash_mismatch',diagnostics['server_stderr'])
        responses=[f for f in diagnostics['frames'] if f['direction']=='server_to_client']
        self.assertEqual(responses,[])

if __name__=='__main__':unittest.main()
