import os,unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from api import create_app
from assistant import Answer,Assistant

class ApiTests(unittest.TestCase):
    def setUp(self):self.context=TestClient(create_app(service=Assistant(),tokens={'reader-demo-token':('demo-reader','reader'),'maintainer-demo-token':('demo-maintainer','maintainer')}));self.client=self.context.__enter__();self.headers={'Authorization':'Bearer reader-demo-token'}
    def tearDown(self):self.context.__exit__(None,None,None)
    def ask(self,body,**kwargs):return self.client.post('/api/ask',json=body,headers=self.headers,**kwargs)
    def test_offline_setup_ignores_inherited_gemini_mode(self):
        with patch.dict(os.environ,{'CAPSTONE_PROVIDER':'gemini','GOOGLE_API_KEY':'not-a-real-key'}),patch('api.Gemini',side_effect=AssertionError('Offline test constructed a model provider')):
            with TestClient(create_app(service=Assistant())) as client:
                result=client.post('/api/ask',json={'question':'deploy staging'},headers=self.headers)
                self.assertEqual(result.status_code,200)
                self.assertEqual(result.json()['trace']['provider'],'extractive')
    def test_authentication_required(self):self.assertEqual(self.client.post('/api/ask',json={'question':'deploy'}).status_code,401)
    def test_unknown_fields_version_and_blank_question(self):
        for body in [{'question':'deploy','version':'9.0'},{'question':'deploy','role':'maintainer'},{'question':'   '}]:self.assertEqual(self.ask(body).status_code,422)
    def test_request_body_is_bounded(self):self.assertEqual(self.client.post('/api/ask',content=b'x'*4097,headers=self.headers).status_code,413)
    def test_duplicate_json_keys_are_refused(self):self.assertEqual(self.client.post('/api/ask',content='{"question":"token","question":"deploy"}',headers=self.headers).status_code,422)
    def test_allowed_answer_and_document(self):
        r=self.ask({'question':'deploy staging'});self.assertEqual(r.status_code,200);self.assertEqual(r.json()['status'],'answered')
        self.assertEqual(self.client.get('/api/sources/deploy-35',headers=self.headers).status_code,200)
    def test_denied_collection_and_document(self):
        self.assertEqual(self.ask({'question':'production','collection':'operations'}).status_code,403)
        self.assertEqual(self.client.get('/api/sources/production-35',headers=self.headers).status_code,403)
    def test_busy_is_http_429(self):
        s=self.client.app.state.assistant;s.slots.acquire();s.slots.acquire()
        try:self.assertEqual(self.ask({'question':'deploy'}).status_code,429)
        finally:s.slots.release();s.slots.release()
    def test_bad_model_citation_is_502_not_an_answer(self):
        class Wrong:
            name='wrong'
            def generate(*a):return Answer(status='answered',answer='Made up',citations=[])
        self.client.app.state.assistant.provider=Wrong()
        r=self.ask({'question':'deploy'});self.assertEqual(r.status_code,502);self.assertNotIn('answer',r.json())
    def test_ui_is_local_and_no_external_scripts(self):
        self.assertEqual(self.client.get('/').status_code,200);self.assertIn('text/html',self.client.get('/').headers['content-type']);self.assertEqual(self.client.get('/app.js').status_code,200)
        self.assertNotIn('https://',self.client.get('/').text)
if __name__=='__main__':unittest.main()
