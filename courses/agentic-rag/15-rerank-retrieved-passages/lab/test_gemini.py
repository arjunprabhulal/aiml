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

from gemini_rerank import apply_order
class RankingTests(unittest.TestCase):
    def test_unknown_duplicate_missing_or_altered_candidate_is_refused(self):
        root=Path(__file__).parent
        baseline=json.loads((root/'runs/2026-10-23-rerank/result.json').read_text())['development_cases'][0]
        snapshot=json.loads((root/'fixtures/snapshot.json').read_text())
        candidates=baseline['before'];ids=[r['chunk_id'] for r in candidates]
        for wrong in [ids+['invented'],ids[:-1],ids+[ids[0]]]:
            with self.assertRaisesRegex(ValueError,'ranking_not_candidate_permutation'):
                apply_order(baseline['query'],candidates,snapshot,{'ranked_ids':wrong})
        changed=[dict(r) for r in candidates];changed[0]['text']='altered'
        with self.assertRaisesRegex(ValueError,'candidate_payload_mismatch'):
            apply_order(baseline['query'],changed,snapshot,{'ranked_ids':ids})
        self.assertEqual([r['chunk_id'] for r in apply_order(baseline['query'],candidates,snapshot,{'ranked_ids':list(reversed(ids))})],list(reversed(ids)))

from gemini_rerank import run as live_run
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
