import json
from pathlib import Path
import unittest
from docuctl_trace import PAGES, digest, evidence_verdict, run
from tracing import parse_traceparent

class DocuctlTrace(unittest.TestCase):
    def test_worker_joins_gateway_trace_and_retains_parent(self):
        result=run();self.assertEqual(len(result['traces']),1)
        spans=result['spans'];parent=next(s for s in spans if s['name']=='lookup.call')
        child=next(s for s in spans if s['service']=='docs-worker')
        self.assertEqual((child['trace_id'],child['parent_id']),(parent['trace_id'],parent['span_id']))
        self.assertFalse(next(iter(result['traces'].values()))['orphans'])
    def test_missing_propagation_creates_a_separate_trace(self):
        result=run(propagate=False);self.assertEqual(len(result['traces']),2)
    def test_invalid_traceparent_is_not_accepted(self):
        for value in ['', '00-'+'0'*32+'-'+'1'*16+'-01','not-a-header']:
            self.assertIsNone(parse_traceparent(value))
    def test_stale_index_is_not_mistaken_for_current_evidence(self):
        result=run(stale=True);self.assertEqual(result['result']['error'],'stale evidence')
        self.assertEqual(next(s for s in result['spans'] if s['name']=='provenance')['status'],'error')
    def test_retrieved_but_dropped_source_is_rejected(self):
        self.assertEqual(run(drop=True)['result']['error'],'citation not sent to answer step')
    def test_unknown_source_is_rejected(self):
        self.assertEqual(evidence_verdict('missing',{},PAGES),'unknown citation')
    def test_blank_question_marks_root_as_failed(self):
        result=run(question=' ');self.assertEqual(result['spans'][0]['status'],'error')
        self.assertNotIn('citation',result['result'])
    def test_telemetry_has_no_question_page_text_or_answer_text(self):
        result=run();serialized=json.dumps(result['spans'])
        self.assertNotIn(PAGES['deploy-35']['text'],serialized)
        self.assertNotIn('Which command',serialized)
        self.assertTrue(any('source_sha256' in s['attributes'] for s in result['spans']))
    def test_current_source_matches_saved_local_receipt(self):
        self.assertEqual(run(),json.loads((Path(__file__).parent/'docuctl-output.json').read_text()))
        self.assertEqual(digest(PAGES['deploy-35']['text']),next(s for s in run()['spans'] if s['name']=='assemble')['attributes']['source_sha256'])
