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

from gemini_stream import application_frames
from stream_core import load_binding,consume,encode_frames
class ProviderTests(unittest.TestCase):
    def event(self,text='',finish=None):
        candidate={'content':{'parts':[{'text':text}]}}
        if finish:candidate['finishReason']=finish
        return {'candidates':[candidate]}
    def test_partial_or_failed_provider_never_accepts_answer(self):
        binding,_=load_binding('utf8-write')
        valid=json.dumps({'status':'not_in_docs','answer':'Not supplied.','source_ids':[]})
        for events in [[self.event(valid)],[self.event(valid,'MAX_TOKENS')]]:
            result=consume([encode_frames(list(application_frames(events,binding)))],binding)
            self.assertIsNone(result['accepted_answer'])
        result=consume([encode_frames(list(application_frames([self.event(valid,'STOP')],binding)))],binding)
        self.assertEqual(result['status'],'complete')
    def test_unknown_source_citation_refuses_even_after_stop(self):
        binding,_=load_binding('utf8-write')
        text=json.dumps({'status':'answered','answer':'Invented.','source_ids':['unknown']})
        result=consume([encode_frames(list(application_frames([self.event(text,'STOP')],binding)))],binding)
        self.assertEqual(result['status'],'invalid');self.assertIsNone(result['accepted_answer'])

from gemini_stream import run as live_run
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
