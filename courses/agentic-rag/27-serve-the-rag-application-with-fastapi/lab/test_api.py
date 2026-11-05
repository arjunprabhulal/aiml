import copy
import json
import hashlib
import unittest
from fastapi.testclient import TestClient
from app import create_app,MAX_BODY_BYTES
from loopback import running_server
from tools import DocumentationTools,load_snapshot
from service import RetrieveRequest,validate_response
from version_documents import canonical_hash

QUESTION='Will write_text replace the contents of an existing file?'

class RealHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=running_server();cls.client,cls.lifecycle=cls.context.__enter__()
    @classmethod
    def tearDownClass(cls):cls.context.__exit__(None,None,None)
    def test_actual_http_health_and_bound_evidence(self):
        health=self.client.get('/health');self.assertEqual(health.status_code,200)
        response=self.client.post('/retrieve',json={'question':QUESTION});self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['X-Retrieval-Body-SHA256'],hashlib.sha256(response.content).hexdigest())
        body=response.json();self.assertEqual(body['status'],'completed');self.assertFalse(body['model_called'])
        self.assertEqual([r['source_id'] for r in body['evidence']],['path-read','path-write'])
        validate_response(body,RetrieveRequest(question=QUESTION),health.json()['corpus_id'])
        self.assertNotIn('answer',body)
    def test_empty_eligible_and_unmatched_question_are_incomplete(self):
        for payload in [{'question':QUESTION,'version':'9.99'},{'question':'How frequently does our cloud provider back up these files?'}]:
            response=self.client.post('/retrieve',json=payload)
            self.assertEqual(response.status_code,200);self.assertEqual(response.json()['status'],'incomplete')
        self.assertEqual(self.client.post('/retrieve',json={'question':QUESTION,'version':'9.99'}).json()['evidence'],[])
    def test_limits_deny_before_read_and_keep_admission_usage(self):
        response=self.client.post('/retrieve',json={'question':QUESTION,'max_source_bytes':0});body=response.json()
        self.assertEqual(response.status_code,200);self.assertEqual(body['status'],'limited');self.assertEqual(body['reason'],'max_source_bytes')
        self.assertEqual(body['usage']['reads'],0);self.assertEqual(body['evidence'],[])
        self.assertFalse(body['trace'][-1]['invoked']);self.assertTrue(body['admission']['accepted'])
    def test_strict_request_invalid_types_extra_fields_and_surrogate(self):
        for payload in [{'question':QUESTION,'max_steps':True},{'question':QUESTION,'version':3.12},{'question':' '},{'question':'x'*513},{'question':QUESTION,'fault':True},{'question':'\ud800'}]:
            # ensure_ascii encodes the deliberate surrogate fixture as valid JSON.
            response=self.client.post('/retrieve',content=json.dumps(payload),headers={'content-type':'application/json'})
            self.assertEqual(response.status_code,422);self.assertEqual(response.json()['error']['code'],'invalid_request')
    def test_malformed_duplicate_json_and_nonfinite_are_safe_422(self):
        for body in [b'{broken',b'{"question":"first","question":"second"}',b'{"question":"x","max_steps":NaN}',b'\xff']:
            response=self.client.post('/retrieve',content=body,headers={'content-type':'application/json'})
            self.assertEqual(response.status_code,422);self.assertEqual(response.json()['error']['code'],'invalid_json')
    def test_chunked_body_bound_without_content_length(self):
        response=self.client.post('/retrieve',content=(piece for piece in [b'{"question":"',b'x'*(MAX_BODY_BYTES+1),b'"}']),headers={'content-type':'application/json'})
        self.assertEqual(response.status_code,413);self.assertFalse(response.json()['admission']['accepted'])
    def test_media_and_offline_docs_routes(self):
        response=self.client.post('/retrieve',content='question',headers={'content-type':'text/plain'})
        self.assertEqual(response.status_code,415)
        for path in ['/docs','/redoc']:self.assertEqual(self.client.get(path).status_code,404)
    def test_response_request_and_digest_tampering_refused(self):
        payload={'question':QUESTION};body=self.client.post('/retrieve',json=payload).json()
        with self.assertRaisesRegex(ValueError,'response_request_mismatch'):validate_response(body,dict(payload,version='3.13'),body['corpus_id'])
        changed=copy.deepcopy(body);changed['evidence'][0]['text']='invented'
        with self.assertRaisesRegex(ValueError,'response_hash_mismatch'):validate_response(changed,payload,body['corpus_id'])
        changed=copy.deepcopy(body);changed['request']['max_steps']=6.0
        changed['result_sha256']=canonical_hash({k:v for k,v in changed.items() if k!='result_sha256'})
        with self.assertRaisesRegex(ValueError,'response_request_mismatch'):validate_response(changed,payload,body['corpus_id'])

class LifecycleAndFaultTests(unittest.TestCase):
    def test_per_request_tools_close_and_invalid_input_never_creates_tools(self):
        instances=[]
        def factory(snapshot):
            tool=DocumentationTools(snapshot);instances.append(tool);return tool
        app=create_app(factory);self.assertFalse(app.state.ready)
        with TestClient(app) as client:
            self.assertTrue(app.state.ready)
            self.assertEqual(client.post('/retrieve',json={'question':QUESTION}).status_code,200)
            self.assertTrue(instances[0].closed)
            client.post('/retrieve',json={'question':QUESTION,'max_steps':True})
            client.post('/retrieve',content=b'x'*(MAX_BODY_BYTES+1),headers={'content-type':'application/json'})
            self.assertEqual(len(instances),1)
        self.assertFalse(app.state.ready);self.assertIsNone(app.state.snapshot)
    def test_real_http_controlled_tool_failure_503_no_private_error_leak(self):
        with running_server('fault_fixture:app') as (client,lifecycle):
            response=client.post('/retrieve',json={'question':QUESTION});body=response.json()
            self.assertEqual(response.headers['X-Retrieval-Body-SHA256'],hashlib.sha256(response.content).hexdigest())
            self.assertEqual(response.status_code,503);self.assertEqual(body['status'],'failed')
            self.assertEqual(body['reason'],'retrieval_failed');self.assertEqual(body['usage']['steps'],1)
            self.assertNotIn('private-detail',response.text);self.assertNotIn('RuntimeError',response.text)
            self.assertEqual(body['evidence'],[])
        self.assertTrue(lifecycle['shutdown_complete_observed']);self.assertTrue(lifecycle['server_process_reaped'])
    def test_unexpected_error_is_generic_without_private_detail(self):
        def factory(snapshot):raise RuntimeError('private_constructor_detail')
        with TestClient(create_app(factory),raise_server_exceptions=False) as client:
            response=client.post('/retrieve',json={'question':QUESTION})
            self.assertEqual(response.status_code,500)
            self.assertEqual(response.json()['error']['code'],'internal_error')
            self.assertNotIn('private_constructor_detail',response.text)
    def test_tool_failure_closes_request_instance(self):
        instances=[]
        class Fault(DocumentationTools):
            def search(self,**args):raise RuntimeError('private detail')
        def factory(snapshot):
            tool=Fault(snapshot);instances.append(tool);return tool
        with TestClient(create_app(factory)) as client:
            response=client.post('/retrieve',json={'question':QUESTION});self.assertEqual(response.status_code,503)
        self.assertTrue(instances[0].closed)

if __name__=='__main__':unittest.main()
