import copy
import hashlib
import json
from pathlib import Path
import unittest
from tools import DocumentationTools,load_snapshot,ToolError,SNAPSHOT_SHA256
from version_documents import canonical_hash

class ToolTests(unittest.TestCase):
    def setUp(self):
        self.snapshot=load_snapshot();self.tools=DocumentationTools(self.snapshot);self.addCleanup(self.tools.close)
    def handle(self):return self.tools.search('overwritten',k=2,version='3.12')['results'][0]
    def test_pinned_snapshot_and_metadata_only_bounded_search(self):
        self.assertEqual(hashlib.sha256((Path(__file__).parent/'fixtures/snapshot.json').read_bytes()).hexdigest(),SNAPSHOT_SHA256)
        result=self.tools.search('text',k=1,version='3.12');self.assertEqual(len(result['results']),1)
        self.assertNotIn('text',result['results'][0]);self.assertNotIn('url',result['results'][0])
        self.assertEqual(result['results'][0]['corpus_id'],self.snapshot['snapshot_id'])
    def test_read_resolves_exact_current_span_and_source_hashes(self):
        handle=self.handle();result=self.tools.read(handle)
        source=next(d for d in self.snapshot['documents'] if d['source_id']=='path-write');chunk=source['chunks'][0]
        self.assertEqual(result['text'],chunk['text']);self.assertEqual(result['source_sha256'],source['sha256'])
        self.assertEqual(result['text_sha256'],chunk['text_sha256']);self.assertEqual((result['start_line'],result['end_line']),(chunk['start_line'],chunk['end_line']))
        self.assertEqual(result['byte_count'],len(result['text'].encode('utf-8')))
        self.assertEqual(self.tools.validate_read(result,handle),result)
    def test_version_filter_is_before_requested_top_k(self):
        result=self.tools.search('text',k=1,version='3.13')
        self.assertEqual(len(result['results']),1);self.assertEqual(result['results'][0]['version'],'3.13')
    def test_empty_and_no_eligible_results_are_explicit(self):
        self.assertEqual(self.tools.search('xyznotindexed')['results'],[])
        self.assertEqual(self.tools.search('overwritten',version='3.13')['results'],[])
    def test_invalid_queries_k_versions_and_unknown_arguments_refused(self):
        for query in ['',None,'text OR newline','../private','https://example.invalid','x'*65]:
            with self.assertRaisesRegex(ToolError,'invalid_query'):self.tools.search(query)
        for k in [True,0,11,1.5,'1']:
            with self.assertRaisesRegex(ToolError,'invalid_k'):self.tools.search('text',k=k)
        for version in [None,True,'latest','3.12 OR 1=1']:
            with self.assertRaisesRegex(ToolError,'invalid_version'):self.tools.search('text',version=version)
        with self.assertRaises(TypeError):self.tools.search('text',path='/private')
    def test_changed_or_rehashed_handle_refused(self):
        for field,value in [('version','3.13'),('source_id','path-read'),('byte_count',0),('text_sha256','changed'),('start_line',99),('rank',True)]:
            changed=dict(self.handle(),**{field:value});changed['read_token']=canonical_hash({k:v for k,v in changed.items() if k!='read_token'})
            with self.subTest(field=field):
                with self.assertRaisesRegex(ToolError,'invalid_read_handle'):self.tools.read(changed)
    def test_unknown_stale_or_unissued_handles_refused(self):
        handle=self.handle()
        for changed,error in [(dict(handle,corpus_id='old'),'stale_corpus'),(dict(handle,passage_id='unknown'),'unknown_passage'),(dict(handle,search_request_id='unissued'),'unissued_search_receipt')]:
            with self.assertRaisesRegex(ToolError,error):self.tools.read(changed)
        other=DocumentationTools(self.snapshot);self.addCleanup(other.close)
        with self.assertRaisesRegex(ToolError,'unissued_search_receipt'):other.read(handle)
    def test_changed_read_payload_even_rehashed_refused(self):
        handle=self.handle();result=self.tools.read(handle)
        for field,value in [('text','invented'),('url','https://example.invalid'),('version','9.0')]:
            changed=dict(result,**{field:value});changed['result_sha256']=canonical_hash({k:v for k,v in changed.items() if k!='result_sha256'})
            with self.assertRaisesRegex(ToolError,'invalid_read_result'):self.tools.validate_read(changed,handle)
    def test_preflight_cost_does_not_invoke_read(self):
        handle=self.handle()
        self.tools.read=lambda handle:(_ for _ in ()).throw(AssertionError('must not read'))
        self.assertEqual(self.tools.read_cost(handle),handle['byte_count'])
        self.assertEqual(self.tools.validate_handle(handle),handle)
    def test_returned_handles_cannot_mutate_issued_receipt(self):
        handle=self.handle();original=copy.deepcopy(handle);handle['byte_count']=0
        self.assertEqual(self.tools.read(original)['byte_count'],original['byte_count'])
    def test_input_snapshot_mutation_cannot_change_current_corpus(self):
        self.snapshot['documents'][0]['text']='changed outside tools'
        self.assertIn('overwritten',self.tools.read(self.handle())['text'])
    def test_closed_tools_refuse_actions(self):
        handle=self.handle();self.tools.close()
        with self.assertRaisesRegex(ToolError,'tools_closed'):self.tools.search('text')
        with self.assertRaisesRegex(ToolError,'tools_closed'):self.tools.read(handle)

if __name__=='__main__':unittest.main()
