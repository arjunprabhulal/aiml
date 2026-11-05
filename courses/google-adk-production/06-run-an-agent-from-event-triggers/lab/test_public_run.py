"""Validate the fresh public execution record without calling providers."""
from pathlib import Path
import hashlib
import json
import unittest
HERE=Path(__file__).resolve().parent
RUN=HERE/'runs/docuctl-2026-10-25'
OPAQUE={'thoughtSignature','thought_signature','functionCallSignature','function_call_signature'}
def keys(v):
    if isinstance(v,dict):
        for k,c in v.items():yield k;yield from keys(c)
    elif isinstance(v,list):
        for c in v:yield from keys(c)
class PublicSelectedRun(unittest.TestCase):
    def test_output_hash_inventory(self):
        receipt=json.loads((RUN/'receipt.json').read_text())
        for name,expected in receipt['files'].items():
            self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(),expected)
    def test_no_opaque_fields_or_database_files(self):
        record=json.loads((HERE/'recorded-runs.json').read_text())
        self.assertFalse(OPAQUE.intersection(keys(record)))
        for p in RUN.rglob('*'):
            if p.is_file():
                self.assertNotEqual(p.suffix,'.db')
                self.assertFalse(p.read_bytes().startswith(b'SQLite format 3\x00'))
    def test_provider_receipts_and_execution_source_binding(self):
        receipt=json.loads((RUN/'receipt.json').read_text())
        self.assertEqual(receipt['execution_mode'],'fresh-local-http-trigger-and-hosted-model')
        self.assertFalse(receipt['cloud_delivery'])
        self.assertGreater(len(receipt['provider_requests']),0)
        for r in receipt['provider_requests']:
            self.assertEqual(r['status'],200)
            self.assertLessEqual(r['max_output_tokens'],8192)
            self.assertEqual(len(r['response_sha256']),64)
            for name,expected in r['source_hashes_at_request'].items():
                self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(),expected,name)
    def test_error_and_delivery_boundaries(self):
        r=json.loads((HERE/'recorded-runs.json').read_text());d=r['deliveries']
        self.assertEqual([x['status']for x in d],[200,200,200,400,401])
        self.assertEqual(r['oidc_missing_token']['status'],401)
        self.assertIsNone(d[3]['session']);self.assertIsNone(d[4]['session'])
        self.assertEqual(d[0]['reviews'],d[1]['reviews']);self.assertEqual(len(d[1]['reviews']),1)
        self.assertIn('DOCUCTL_TOKEN',d[1]['reviews'][0]['summary']);self.assertIn('90 days',d[1]['reviews'][0]['summary'])
        calls=[p.get('functionCall',{})for x in d[:2]for t in x['session']['model_turns']for p in t['content']['parts']]
        writes=[c for c in calls if c.get('name')=='post_review']
        self.assertEqual(len(writes),2)
        self.assertTrue(all(c['args']['page']=='tokens'for c in writes))
if __name__=='__main__':unittest.main()
