"""Owned inspector contracts through the actual local HTTP boundary and client JS."""
from pathlib import Path
import hashlib
import json
import subprocess
import unittest
from loopback import running_server

QUESTION='Will write_text replace the contents of an existing file?'

class InspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=running_server('inspector_app:app');cls.client,cls.lifecycle=cls.context.__enter__()
    @classmethod
    def tearDownClass(cls):cls.context.__exit__(None,None,None)
    def test_actual_static_assets_and_same_origin_api(self):
        html=self.client.get('/inspector');self.assertEqual(html.status_code,200)
        self.assertIn('/inspector-assets/inspector.js',html.text)
        for path in ['inspector.js','inspector.css','fonts/ibm-plex-sans-latin-400-normal.woff2','fonts/dm-sans-latin-600-normal.woff2']:
            self.assertEqual(self.client.get('/inspector-assets/'+path).status_code,200)
        response=self.client.post('/retrieve',json={'question':QUESTION});self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['status'],'completed');self.assertFalse(response.json()['model_called'])
        self.assertEqual(hashlib.sha256(response.content).hexdigest(),response.headers['x-retrieval-body-sha256'])
    def test_empty_and_limited_are_distinct_from_http_errors(self):
        empty=self.client.post('/retrieve',json={'question':QUESTION,'version':'9.99'});self.assertEqual(empty.status_code,200);self.assertEqual(empty.json()['status'],'incomplete');self.assertEqual(empty.json()['evidence'],[])
        limited=self.client.post('/retrieve',json={'question':QUESTION,'max_steps':0});self.assertEqual(limited.status_code,200);self.assertEqual(limited.json()['status'],'limited');self.assertEqual(limited.json()['usage']['steps'],0)
        self.assertEqual(self.client.post('/retrieve',json={'question':' '}).status_code,422)
    def test_real_controlled_service_failure_is_not_a_success(self):
        with running_server('inspector_fixtures:fault_app') as (client,lifecycle):
            response=client.post('/retrieve',json={'question':QUESTION});self.assertEqual(response.status_code,503);self.assertEqual(response.json()['status'],'failed');self.assertEqual(response.json()['evidence'],[])
        self.assertTrue(lifecycle['shutdown_complete_observed']);self.assertTrue(lifecycle['server_process_reaped'])
    def test_client_request_wire_and_evidence_guards(self):
        completed=subprocess.run(['node','--test','test_inspector.mjs'],cwd=Path(__file__).parent,capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)

if __name__=='__main__':unittest.main()
