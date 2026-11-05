import unittest
from schema_policy import SchemaPolicy,offered_context,MAX_MODEL_CALLS
from tools import DocumentationTools,load_snapshot
from gemini_policy import LIMITS
from limits import run_limited

class Fake:
 def __init__(self,rows):self.rows=iter(rows);self.requests=[]
 def generate(self,system,user,schema):
  self.requests.append((system,user,schema));return {'decision':next(self.rows)}

class SchemaTests(unittest.TestCase):
 def test_unoffered_query_and_unissued_reference_are_refused(self):
  for d in ({'action':'search','query':'write_text'},{'action':'read','handle_id':'r99'},{'action':'shell'}):
   with self.subTest(d=d):
    with self.assertRaises(ValueError):SchemaPolicy('write text','3.12',Fake([d]))([])
 def test_schema_offers_words_and_no_unissued_read(self):
  client=Fake([{'action':'stop','status':'incomplete','reason':'no evidence'}]);SchemaPolicy('write_text file','3.12',client)([])
  schema=client.requests[0][2]['properties']['decision']['anyOf']
  self.assertEqual(schema[0]['properties']['query']['enum'],['file','text','write'])
  self.assertEqual(len(schema),2)
 def test_read_reference_resolves_to_host_issued_handle(self):
  client=Fake([{'action':'search','query':'overwritten'},{'action':'read','handle_id':'r1'},{'action':'stop','status':'completed','reason':'read source'}])
  tools=DocumentationTools(load_snapshot())
  try:result=run_limited(tools,SchemaPolicy('What overwritten a file?','3.12',client),LIMITS)
  finally:tools.close()
  self.assertEqual(result['observations'][1]['tool'],'read')
  self.assertNotIn('target_sources',client.requests[0][1])
  self.assertNotIn('sha256',client.requests[1][1])
 def test_request_cap_stops_before_another_call(self):
  client=Fake([{'action':'stop','status':'incomplete','reason':'stop'}]*MAX_MODEL_CALLS)
  p=SchemaPolicy('text','3.12',client)
  for _ in range(MAX_MODEL_CALLS):p([])
  self.assertIsNone(p([]));self.assertEqual(len(client.requests),MAX_MODEL_CALLS)

class RecordedSchemaTests(unittest.TestCase):
 def test_frozen_benchmark_replays_every_request_offline(self):
  import json
  from pathlib import Path
  from test_gemini import RecordedClient
  from benchmark import run
  client=RecordedClient();client.records=[json.loads(p.read_text()) for p in sorted((Path(__file__).parent/'runs/gemini-schema-v2/requests').glob('request-*.json'))];client.cursor=0;client.calls=[]
  actual=run(client);expected=json.loads((Path(__file__).parent/'runs/gemini-schema-v2/result.json').read_text())
  actual.pop('calls');expected.pop('calls');self.assertEqual(actual,expected);self.assertEqual(client.cursor,len(client.records))

if __name__=='__main__':unittest.main()
