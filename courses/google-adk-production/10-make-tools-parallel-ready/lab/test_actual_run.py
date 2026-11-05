"""Bind the fresh Runner records to captured provider bodies and executed source."""
from pathlib import Path
import hashlib
import json
import unittest
HERE=Path(__file__).resolve().parent
RUN=HERE/'runs/docuctl-2026-10-25'
M=json.loads((RUN/'manifest.json').read_text())
P=json.loads((RUN/'provider-projection.json').read_text())
class FreshProviderEvidence(unittest.TestCase):
 def test_public_records_match_bound_bytes(self):
  for name,expected in M['files_sha256'].items():
   self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(),expected,name)
 def test_actual_requests_used_current_sources_and_explicit_cap(self):
  self.assertEqual(len(P['requests']),M['provider_attempts'])
  self.assertGreater(len(P['requests']),0)
  for row in P['requests']:
   self.assertEqual(row['status'],200)
   self.assertGreaterEqual(row['finished_epoch'],row['started_epoch'])
   self.assertEqual(len(row['original_private_response_sha256']),64)
   for name,expected in row['executed_source_sha256'].items():
    self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(),expected,name)
   self.assertEqual(row['request']['generationConfig']['maxOutputTokens'],8192)
 def test_opaque_fields_are_omitted_without_reconstructing_native_capture(self):
  def check(value):
   if isinstance(value,dict):
    self.assertNotIn('thoughtSignature',value);self.assertNotIn('thought_signature',value)
    for child in value.values():check(child)
   elif isinstance(value,list):
    for child in value:check(child)
  check(P['requests'])
if __name__=='__main__':unittest.main()
