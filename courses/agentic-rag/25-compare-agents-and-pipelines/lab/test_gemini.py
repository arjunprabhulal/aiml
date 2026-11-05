import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gemini_client import Gemini,reserve,sse_json

class BudgetTests(unittest.TestCase):
    def test_budget_refuses_before_credential_or_network(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=Path(d)/'ledger.json'
            for _ in range(80):reserve(ledger,'fixture')
            with patch('gemini_client.urllib.request.urlopen') as network:
                with self.assertRaisesRegex(ValueError,'budget_exhausted'):
                    list(Gemini(ledger,Path(d)/'requests').request('x','y'))
                network.assert_not_called()
    def test_oversized_input_refuses_without_reservation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger.json'
            with self.assertRaisesRegex(ValueError,'request_byte_limit'):
                list(Gemini(p,Path(d)/'requests').request('x','y'*60001))
            self.assertFalse(p.exists())
    def test_sse_preserves_events_and_rejects_truncation(self):
        self.assertEqual(list(sse_json(io.BytesIO(b'data: {"x":1}\r\n\r\n'))),[{'x':1}])
        with self.assertRaisesRegex(ValueError,'truncated_provider_event'):
            list(sse_json(io.BytesIO(b'data: {"x":1}\n')))

from gemini_policy import GeminiPolicy,LIMITS
from limits import run_limited
from tools import DocumentationTools,load_snapshot
class FakeClient:
    def __init__(self,actions):self.actions=iter(actions);self.requests=[]
    def generate(self,system,user):self.requests.append(json.loads(user));return next(self.actions)
class PolicyTests(unittest.TestCase):
    def test_model_cannot_invoke_unissued_read_or_invalid_tool(self):
        for action in [{'tool':'read','arguments':{'handle':{}}},{'tool':'shell','arguments':{}}]:
            tools=DocumentationTools(load_snapshot())
            try:
                client=FakeClient([action]);policy=GeminiPolicy('Question','3.12',client)
                result=run_limited(tools,policy,LIMITS)
                self.assertEqual(result['controller_status'],'failed')
                self.assertEqual(result['usage']['steps'],0)
                self.assertEqual(set(client.requests[0]),{'question','version','observations'})
            finally:tools.close()
    def test_model_call_guard_stops_before_eighth_request(self):
        client=FakeClient([{'tool':'search','arguments':{'query':'text','version':'3.12','k':2}}]*7)
        policy=GeminiPolicy('Question','3.12',client)
        for _ in range(7):policy([])
        self.assertIsNone(policy([]));self.assertEqual(len(client.requests),7)

from gemini_policy import run as live_run
from gemini_client import digest,CONFIG,text_of
class RecordedClient:
    def __init__(self):
        self.records=[json.loads(p.read_text()) for p in sorted((Path(__file__).parent/'runs/2026-10-24-gemini/requests').glob('request-*.json'))]
        self.records=[r for r in self.records if 'error' not in r]
        self.cursor=0;self.calls=[]
    def request(self,system,user,*,stream=False,schema=None):
        record=self.records[self.cursor];self.cursor+=1
        config=dict(CONFIG)
        if schema is not None:config['responseJsonSchema']=schema
        payload={'systemInstruction':{'parts':[{'text':system}]},'contents':[{'role':'user','parts':[{'text':user}]}],'generationConfig':config}
        if digest(payload)!=record['request_sha256'] or record['stream']!=stream:
            raise ValueError('replay_request_mismatch')
        for event in record['responses']:yield event['payload']
    def generate(self,system,user,schema=None):
        return json.loads(text_of(list(self.request(system,user,schema=schema))[0]))
class RecordedRunTests(unittest.TestCase):
    def test_actual_execution_replays_exact_recorded_requests_offline(self):
        client=RecordedClient();actual=live_run(client)
        expected=json.loads((Path(__file__).parent/'runs/2026-10-24-gemini/result.json').read_text())
        actual.pop('calls');expected.pop('calls')
        self.assertEqual(actual,expected)
        self.assertEqual(client.cursor,len(client.records))
    def test_changed_prompt_refuses_recording(self):
        with self.assertRaisesRegex(ValueError,'replay_request_mismatch'):
            list(RecordedClient().request('changed','changed'))

class ValidToolPathTests(unittest.TestCase):
    def test_valid_search_and_issued_read_reach_real_tools(self):
        class Client:
            def generate(self,system,user):
                observations=json.loads(user)['observations']
                if not observations:return {'tool':'search','arguments':{'query':'overwritten','version':'3.12','k':2}}
                if len(observations)==1:return {'tool':'read','arguments':{'handle':observations[0]['result']['results'][0]}}
                return {'tool':'stop','arguments':{'status':'completed','reason':'Read supplied passage.'}}
        tools=DocumentationTools(load_snapshot())
        try:
            policy=GeminiPolicy('Save text','3.12',Client())
            result=run_limited(tools,policy,LIMITS)
            self.assertEqual(result['controller_status'],'completed')
            self.assertEqual(result['usage']['searches'],1)
            self.assertEqual(result['usage']['reads'],1)
            self.assertTrue(all(event['invoked'] for event in result['trace']))
            self.assertIn('write_text',result['observations'][-1]['result']['text'])
        finally:tools.close()
