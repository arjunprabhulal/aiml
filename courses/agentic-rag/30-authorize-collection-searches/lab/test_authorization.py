import copy
import unittest
from fastapi.testclient import TestClient
from app import create_app
from authorization import Authorization,AccessError

REQUEST={'query':'file','collection':'files','version':'3.12','k':2}
class AuthorizationTests(unittest.TestCase):
    def setUp(self):self.engine=Authorization()
    def test_unknown_identity_refused(self):
        with self.assertRaises(AccessError):self.engine.resolve('Bearer unknown')
    def test_denial_before_tool_construction(self):
        def forbidden(snapshot):raise AssertionError('tool invoked')
        self.engine.tool_factory=forbidden
        with self.assertRaises(AccessError):self.engine.search('reader',REQUEST)
        self.assertEqual(self.engine.search_calls,0)
    def test_eligibility_before_k(self):
        result=self.engine.search('editor',{'query':'file','collection':'serialization','version':'3.12','k':1})
        self.assertEqual([h['source_id'] for h in result['results']],['json-text'])
    def test_foreign_handle_refused(self):
        handle=self.engine.search('editor',{'query':'json','collection':'serialization','version':'3.12','k':1})['results'][0]
        with self.assertRaises(AccessError):self.engine.read('reader',handle)
        self.assertEqual(self.engine.read_calls,0)
    def test_tampered_handle_refused(self):
        h=self.engine.search('editor',REQUEST)['results'][0];h['start_line']+=1
        with self.assertRaises(AccessError):self.engine.read('editor',h)
    def test_policy_revision_and_revoked_grant_refused(self):
        h=self.engine.search('editor',REQUEST)['results'][0];self.engine.policy['grants']['editor']=['serialization']
        with self.assertRaises(AccessError):self.engine.read('editor',h)
    def test_stale_corpus_refused(self):
        h=self.engine.search('editor',REQUEST)['results'][0];self.engine.corpus_id='different'
        with self.assertRaises(AccessError):self.engine.read('editor',h)
    def test_malformed_collection_safe(self):
        with self.assertRaises(AccessError):self.engine.read('editor',{'collection':[]})
    def test_fakeclock_expiry_and_capacity(self):
        now=[0.0];engine=Authorization(clock=lambda:now[0],max_handles=1,handle_ttl=1)
        first=engine.search('editor',{**REQUEST,'k':1})['results'][0]
        engine.search('editor',{**REQUEST,'k':1})
        with self.assertRaises(AccessError):engine.read('editor',first)
        last=next(iter(engine.issued.values()))[1];now[0]=1
        with self.assertRaises(AccessError):engine.read('editor',last)
    def test_http_validation_and_success(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.post('/search',json=REQUEST).status_code,401)
            self.assertEqual(client.post('/search',json={**REQUEST,'k':True},headers={'Authorization':'Bearer demo-editor'}).status_code,422)
            r=client.post('/search',json=REQUEST,headers={'Authorization':'Bearer demo-editor'});self.assertEqual(r.status_code,200)
            h=r.json()['results'][0]
            self.assertEqual(client.post('/read',json={'handle':h},headers={'Authorization':'Bearer demo-editor'}).status_code,200)
            self.assertEqual(client.post('/read',json={'handle':h},headers={'Authorization':'Bearer demo-reader'}).status_code,403)
    def test_http_tool_failure_safe(self):
        def fault(snapshot):raise RuntimeError('SECRET PATH')
        with TestClient(create_app(lambda:Authorization(tool_factory=fault))) as client:
            r=client.post('/search',json=REQUEST,headers={'Authorization':'Bearer demo-editor'})
            self.assertEqual(r.status_code,503);self.assertEqual(r.json(),{'error':{'code':'tool_failure'}})
if __name__=='__main__':unittest.main()

class CorpusBoundTests(unittest.TestCase):
    def test_corpus_over_100_rejected(self):
        from unittest.mock import patch
        from tools import DocumentationTools,ToolError,load_snapshot
        snapshot=load_snapshot();document=snapshot['documents'][0]
        document['chunks']=[{**document['chunks'][0],'chunk_id':str(i)} for i in range(101)]
        # Isolate the explicit operational bound after the independent snapshot validator.
        with patch('tools.validate_snapshot'),patch('tools.LexicalIndex'):
            with self.assertRaises(ToolError):DocumentationTools(snapshot)

class RealHTTPTests(unittest.TestCase):
    def test_real_http_body_and_authorization_boundary(self):
        import tempfile
        from pathlib import Path
        from local_http import server
        with tempfile.TemporaryDirectory() as logs,server(Path(__file__).parent,logs) as client:
            self.assertEqual(client.post('/search',json=REQUEST,headers={'Authorization':'Bearer unknown'}).status_code,401)
            self.assertEqual(client.post('/search',content=b'{"k":1,"k":2}',headers={'Content-Type':'application/json'}).status_code,422)
            self.assertEqual(client.post('/search',content=b'x'*8193,headers={'Content-Type':'application/json'}).status_code,413)
            r=client.post('/search',json=REQUEST,headers={'Authorization':'Bearer demo-editor'});self.assertEqual(r.status_code,200)
            self.assertEqual(client.post('/read',json={'handle':r.json()['results'][0]},headers={'Authorization':'Bearer demo-editor'}).status_code,200)
