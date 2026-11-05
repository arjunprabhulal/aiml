"""Offline unit/contract tests. Fakes are controlled data, never model records."""
from __future__ import annotations
import copy
from contextlib import redirect_stdout
import io,json,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx
import baseline
import baseline_lib as lib
import baseline_task
from local_models import CallGuard,LimitError

NETWORK=[]
def no_network(*a,**kw):NETWORK.append(1);raise AssertionError('Offline test attempted network')


class FakeModels:
 mode='controlled_unit_fake_not_model_output'
 models=lib.MODEL_DIGESTS
 def __init__(self,cases,malformed=None,false_claim=False):
  self.cases={c['input']:c for c in cases['cases']};self.malformed=malformed;self.false_claim=false_claim
  self.docs=lib.chunks();self.query_calls=[];self.generate_calls=[];self.document_calls=0
 def documents(self,texts):
  self.document_calls+=1
  return [[float(i==j)for j in range(4)]for i in range(4)]
 def query(self,case_id,question):
  self.query_calls.append(case_id);case=self.cases[question]
  source=case['expected']['targets'][0]['source_id']if case['expected']['targets']else self.docs[0].metadata['id']
  i=next(i for i,d in enumerate(self.docs)if d.metadata['id']==source)
  return [float(i==j)for j in range(4)]
 def generate(self,case_id,question,messages):
  self.generate_calls.append(case_id)
  payload=json.loads(messages[-1][1]);assert set(payload)=={'question','context'}
  assert all(set(p)=={'id','text'}for p in payload['context'])
  case=self.cases[question]
  if case_id==self.malformed:return {'raw':{'content':'{bad JSON','response_metadata':{'done_reason':'stop'}},'parsed':None,'parsing_error':'controlled parse error'}
  ids=[t['source_id']for t in case['expected']['targets']]
  answer='write_text appends instead of overwriting.'if self.false_claim else'Controlled unit-test output, not a generated model answer.'
  return {'raw':{'content':'controlled unit fake'},'parsed':{'status':case['expected']['status'],'answer':answer,'source_ids':ids},'parsing_error':None}


class BaselineTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.patches=[patch('socket.socket.connect',no_network),patch('socket.socket.connect_ex',no_network),patch('socket.getaddrinfo',no_network)]
  for p in cls.patches:p.start()
 @classmethod
 def tearDownClass(cls):
  for p in reversed(cls.patches):p.stop()
  if NETWORK:raise AssertionError('Network attempted in offline tests')
 def setUp(self):self.cases,_,_=lib.load_frozen()
 def all_plan(self):return lib.plan(['development','held_out'],True)
 def fake_record(self,folder,malformed=None,false_claim=False):
  plan=self.all_plan();models=FakeModels(self.cases,malformed,false_claim)
  guard=CallGuard(plan,[d.page_content for d in lib.chunks()])
  binding=baseline.record_once(folder,plan,models,guard,mode=models.mode)
  return binding,models
 def test_frozen_dataset_pipeline_core_and_metric_source_parity(self):
  proof=lib.verify_reuse();self.assertEqual(proof['unchanged_reuse_files'],18)
  self.assertEqual(self.cases['sha256'],lib.DATASET_SHA)
  self.assertEqual(len(lib.chunks()),4)
 def test_archived_source_matches_the_recording_and_current_runtime(self):
  run=lib.ROOT/'runs/20261023T002037.167760Z-fixed-eight-local-baseline'
  manifest=lib.read(run/'run-manifest.json');snapshot=run/'source'
  self.assertEqual(len(manifest['source_hashes']),27)
  for rel,expected in manifest['source_hashes'].items():
   self.assertEqual(lib.sha((snapshot/rel).read_bytes()),expected,rel)
   if rel not in ('README.md','test_baseline.py'):
    self.assertEqual((lib.ROOT/rel).read_bytes(),(snapshot/rel).read_bytes(),rel)
  self.assertNotEqual((lib.ROOT/'README.md').read_bytes(),(snapshot/'README.md').read_bytes())
 def test_archived_source_replays_without_network_or_new_answers(self):
  import os,subprocess,sys
  run=lib.ROOT/'runs/20261023T002037.167760Z-fixed-eight-local-baseline'
  code="""import runpy,socket,sys
from pathlib import Path
def deny(*a,**k):raise AssertionError('Saved replay attempted network')
socket.socket.connect=deny;socket.socket.connect_ex=deny;socket.create_connection=deny;socket.getaddrinfo=deny
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'source'))
sys.argv=[str(root/'source/baseline.py'),'replay','--record',str(root)]
runpy.run_path(sys.argv[0],run_name='__main__')
"""
  env={k:v for k,v in os.environ.items() if k not in ('GOOGLE_API_KEY','GEMINI_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','GOOGLE_APPLICATION_CREDENTIALS')}
  result=subprocess.run([sys.executable,'-c',code,str(run)],env=env,capture_output=True,text=True,timeout=60)
  self.assertEqual(result.returncode,0,result.stderr)
  parsed=json.loads(result.stdout)
  self.assertEqual(parsed['measurements'],lib.read(run/'measurements.json'))
  self.assertEqual(parsed['automatic_contracts']['summary'],lib.read(run/'automatic-contracts.json')['summary'])
 def test_default_plan_is_offline_and_development_only(self):
  with redirect_stdout(io.StringIO())as out:self.assertEqual(baseline.main([]),0)
  plan=json.loads(out.getvalue());self.assertEqual(plan['splits'],['development']);self.assertEqual(len(plan['case_ids']),4)
  self.assertEqual(plan['max_inference_http_calls'],9)
 def test_held_out_is_explicit_and_plan_has_17_cap(self):
  with self.assertRaises(lib.harness.RunError):lib.plan(['development','held_out'])
  plan=self.all_plan();self.assertEqual(len(plan['case_ids']),8);self.assertEqual(plan['max_inference_http_calls'],17)
  self.assertEqual(plan['requested_generation_token_ceiling'],3200)
 def test_no_fresh_execution_without_flag_and_reviewed_hash(self):
  for args in (['record'],['record','--fresh-local'],['record','--fresh-local','--reviewed-code-sha256','wrong']):
   with self.assertRaises(ValueError):baseline.main(args)
 def test_more_than_one_trial_is_refused(self):
  with self.assertRaises(ValueError):baseline.main(['plan','--trials','2'])
 def test_existing_outputs_are_never_overwritten(self):
  with tempfile.TemporaryDirectory()as t:
   marker=Path(t)/'keep';marker.write_text('unchanged')
   with self.assertRaises(FileExistsError):baseline.main(['record','--fresh-local','--reviewed-code-sha256',lib.code_bundle_sha(),'--out',t])
   self.assertEqual(marker.read_text(),'unchanged')
 def test_fake_8_case_record_once_then_replay_never_regenerates(self):
  with tempfile.TemporaryDirectory()as t:
   folder=Path(t);_,models=self.fake_record(folder)
   self.assertEqual(models.document_calls,1);self.assertEqual(len(models.query_calls),8);self.assertEqual(len(models.generate_calls),8)
   result=baseline.replay(folder);self.assertEqual(len(models.generate_calls),8)
   self.assertEqual(set(result['measurements']['by_split']),{'development','held_out'})
   self.assertEqual(result['measurements']['by_split']['development']['supported'],3)
   self.assertEqual(result['measurements']['by_split']['held_out']['supported'],2)
   self.assertTrue(all(r['human_semantic_verdict']=='unreviewed'for r in result['measurements']['rows']))
 def test_unsupported_retrieval_is_null_not_perfect(self):
  with tempfile.TemporaryDirectory()as t:
   self.fake_record(Path(t));rows=lib.read(Path(t)/'measurements.json')['rows']
   unsupported=[r for r in rows if not r['annotated_target_chunk_ids']]
   self.assertEqual(len(unsupported),3);self.assertTrue(all(r['retrieval']is None for r in unsupported))
 def test_wrong_version_is_not_a_retrieval_hit(self):
  cases={c['id']:c for c in self.cases['cases']}
  got=lib.retrieval_scores([cases['read-newline-313']['expected']['targets'][0]['chunk_id']],
   [cases['read-newline-312']['expected']['targets'][0]['chunk_id']])
  self.assertEqual(got,{'hit':False,'recall':0.0,'reciprocal_rank':0.0})
 def test_reused_rank2_miss_and_empty_target_semantics(self):
  self.assertEqual(lib.retrieval_scores(['a','b'],['b']),{'hit':True,'recall':1.0,'reciprocal_rank':.5})
  self.assertEqual(lib.retrieval_scores(['a','c'],['b']),{'hit':False,'recall':0.0,'reciprocal_rank':0.0})
  self.assertIsNone(lib.retrieval_scores(['a'],[]))
 def test_invalid_json_retained_once_and_counted_incomplete(self):
  with tempfile.TemporaryDirectory()as t:
   folder=Path(t);_,models=self.fake_record(folder,malformed='utf8-write')
   recording=lib.read(folder/'recording.json');raw=lib.read(folder/'case-observations.json')
   self.assertEqual(models.generate_calls.count('utf8-write'),1)
   self.assertIn('error',recording['responses']['utf8-write'][0])
   self.assertEqual(raw['utf8-write']['generation']['raw']['content'],'{bad JSON')
   rows=lib.read(folder/'measurements.json')['rows'];row=next(r for r in rows if r['case_id']=='utf8-write')
   self.assertIsNone(row['reply_status']);self.assertIsNotNone(row['error']);self.assertIsNotNone(row['retrieval'])
 def test_legal_id_false_claim_is_not_automatic_semantic_success(self):
  case=self.cases['cases'][1]
  output={'status':'answered','answer':'write_text appends instead of overwriting.','source_ids':['path-write'],'context_ids':['path-write']}
  self.assertTrue(all(g['check'](case,output)[0]for g in baseline_task.GRADERS))
  with tempfile.TemporaryDirectory()as t:
   self.fake_record(Path(t),false_claim=True)
   review=lib.read(Path(t)/'human-review.json')
   self.assertTrue(all(v['verdict']=='unreviewed'for v in review['cases'].values()))
 def test_replay_refuses_artifact_change_instead_of_new_inference(self):
  with tempfile.TemporaryDirectory()as t:
   folder=Path(t);_,models=self.fake_record(folder)
   p=folder/'case-observations.json';p.write_text('{}')
   with self.assertRaisesRegex(ValueError,'artifact'):baseline.replay(folder)
   self.assertEqual(len(models.generate_calls),8)
 def test_missing_usage_remains_missing(self):
  with tempfile.TemporaryDirectory()as t:
   self.fake_record(Path(t));rows=lib.read(Path(t)/'measurements.json')['rows']
   self.assertTrue(all(r['usage_metadata']is None for r in rows))
 def test_false_answers_abstentions_and_errors_keep_original_denominators(self):
  with tempfile.TemporaryDirectory()as t:
   folder=Path(t);self.fake_record(folder)
   recording=lib.read(folder/'recording.json');observations=lib.read(folder/'case-observations.json')
   recording['responses']['utf8-write'][0]['output'].update(status='not_in_docs',source_ids=[])
   recording['responses']['backup-schedule'][0]['output'].update(status='answered',answer='Unsupported policy claim',source_ids=['path-write'])
   recording['responses']['json-throughput'][0]={'error':{'types':['ValueError'],'message':'controlled parse failure'},'latency_s':0.0}
   result=lib.annotate(recording,observations,self.cases)
   dev=result['by_split']['development'];held=result['by_split']['held_out']
   self.assertEqual(dev['cases'],4);self.assertEqual(dev['false_answer_on_unsupported'],1);self.assertEqual(dev['false_abstention_on_supported'],1)
   self.assertEqual(held['cases'],4);self.assertEqual(held['unsupported'],2);self.assertEqual(held['missing_or_error_outputs'],1)
   self.assertIsNone(next(r for r in result['rows']if r['case_id']=='json-throughput')['status_matches_annotation'])
 def test_unchanged_prompt_receives_no_expected_tags_or_oracle_version(self):
  with tempfile.TemporaryDirectory()as t:
   self.fake_record(Path(t));rows=lib.read(Path(t)/'case-observations.json')
   for obs in rows.values():
    payload=json.loads(obs['messages'][-1][1]);self.assertEqual(set(payload),{'question','context'})
    self.assertNotIn('expected',payload);self.assertNotIn('python_version',payload)
    self.assertEqual(payload['question'],next(c['input']for c in self.cases['cases']if c['id']==obs['case_id']))
 def test_query_instruction_is_exact(self):
  q=self.cases['cases'][0]['input']
  self.assertEqual(lib.query_text(q),'Instruct: Retrieve Python documentation that answers the developer question\nQuery: '+q)

 def request(self,path,body):return httpx.Request('POST','http://127.0.0.1:11434'+path,json=body)
 def test_guard_caps_each_query_and_generation_without_retry(self):
  plan=self.all_plan();guard=CallGuard(plan,[d.page_content for d in lib.chunks()]);case=plan['case_ids'][0]
  guard.expect('query',case,text='exact')
  req=self.request('/api/embed',{'model':lib.EMBED,'input':['exact']})
  guard.before(req)
  with self.assertRaises(LimitError):guard.before(req)
  messages=[('system','exact system'),('human','exact question')];guard.expect('generation',case,messages=messages)
  body={'model':lib.MODEL,'messages':[{'role':'system','content':'exact system'},{'role':'user','content':'exact question'}],
   'options':{'temperature':0,'num_predict':400},'stream':True,'format':lib.Reply.model_json_schema()}
  req=self.request('/api/chat',body);guard.before(req)
  with self.assertRaises(LimitError):guard.before(req)
  self.assertEqual(sum(guard.counts['generation'].values()),1)
 def test_guard_rejects_model_pull_provider_and_option_changes(self):
  guard=CallGuard(self.all_plan(),[d.page_content for d in lib.chunks()])
  for req in (self.request('/api/pull',{'model':lib.MODEL}),httpx.Request('GET','https://generativelanguage.googleapis.com/')):
   with self.assertRaises(LimitError):guard.before(req)
  guard.expect('generation',self.all_plan()['case_ids'][0],messages=[('human','q')])
  base={'model':lib.MODEL,'messages':[{'role':'user','content':'q'}],'options':{'temperature':0,'num_predict':401},'format':lib.Reply.model_json_schema()}
  with self.assertRaises(LimitError):guard.before(self.request('/api/chat',base))
  self.assertEqual(guard.counts['generation'],{})
 def test_guard_total_cap_and_exact_document_batch(self):
  plan=self.all_plan();plan['max_inference_http_calls']=1
  texts=[d.page_content for d in lib.chunks()];guard=CallGuard(plan,texts);guard.expect('documents')
  with self.assertRaises(LimitError):guard.before(self.request('/api/embed',{'model':lib.EMBED,'input':['wrong']}))
  guard.before(self.request('/api/embed',{'model':lib.EMBED,'input':texts}))
  guard.expect('query',plan['case_ids'][0],text='q')
  with self.assertRaises(LimitError):guard.before(self.request('/api/embed',{'model':lib.EMBED,'input':['q']}))
  self.assertEqual(guard.counts['queries'],{})
 def test_installed_parser_observation_does_not_retry_or_change_request(self):
  from langchain_ollama import ChatOllama
  from langchain_core.messages import AIMessage
  from langchain_core.outputs import ChatResult,ChatGeneration
  calls=[]
  def fake_generate(instance,messages,stop=None,run_manager=None,**kwargs):
   calls.append({'messages':[(m.type,m.content)for m in messages],'kwargs':kwargs})
   return ChatResult(generations=[ChatGeneration(message=AIMessage(content='not JSON'))])
  model=ChatOllama(model=lib.MODEL,base_url='http://127.0.0.1:11434',temperature=0,num_predict=400)
  with patch.object(ChatOllama,'_generate',fake_generate):
   observed=model.with_structured_output(lib.Reply,include_raw=True).invoke([('human','q')])
   self.assertEqual(len(calls),1);self.assertIsNone(observed['parsed']);self.assertIsNotNone(observed['parsing_error'])
   self.assertEqual(observed['raw'].content,'not JSON')
   with self.assertRaises(Exception):model.with_structured_output(lib.Reply).invoke([('human','q')])
  self.assertEqual(len(calls),2);self.assertEqual(calls[0],calls[1])

class InstalledWireTests(unittest.TestCase):
 def test_actual_installed_ollama_sdk_passes_guard_with_mock_http_only(self):
  from local_models import FreshModels
  plan=lib.plan(['development']);texts=[d.page_content for d in lib.chunks()]
  guard=CallGuard(plan,texts);calls=[]
  def fake_send(client,request,*a,**kw):
   calls.append(str(request.url));body=json.loads(request.content)if request.content else{}
   if request.url.path=='/api/tags':
    payload={'models':[{'name':k,'model':k,'digest':v}for k,v in lib.MODEL_DIGESTS.items()]}
   elif request.url.path=='/api/embed':
    inp=body['input'];items=inp if isinstance(inp,list)else[inp]
    payload={'model':lib.EMBED,'embeddings':[[1.,0.,0.,0.]for _ in items],'prompt_eval_count':9}
   elif request.url.path=='/api/chat':
    payload={'model':lib.MODEL,'created_at':'2026-10-22T00:00:00Z','message':{'role':'assistant','content':json.dumps({'status':'answered','answer':'Controlled fake SDK reply.','source_ids':['path-write']})},
     'done':True,'done_reason':'stop','prompt_eval_count':13,'eval_count':7,'total_duration':1000}
   else:raise AssertionError('Unexpected fake route')
   return httpx.Response(200,stream=httpx.ByteStream((json.dumps(payload)+'\n').encode()),request=request)
  with patch.object(httpx.Client,'send',fake_send),patch('socket.socket.connect',no_network),patch('socket.getaddrinfo',no_network):
   with guard.installed():
    models=FreshModels(guard);self.assertEqual(len(models.documents(texts)),4)
    c=lib.load_frozen()[0]['cases'][0];self.assertEqual(len(models.query(c['id'],c['input'])),4)
    result=models.generate(c['id'],c['input'],[('system','exact system'),('human','exact question')])
  self.assertIsNone(result['parsing_error']);self.assertEqual(result['parsed']['source_ids'],['path-write'])
  self.assertEqual(result['raw']['usage_metadata']['input_tokens'],13)
  self.assertEqual(result['raw']['usage_metadata']['output_tokens'],7)
  self.assertEqual(guard.counts,{'documents':1,'queries':{c['id']:1},'generation':{c['id']:1},'metadata':1})
  self.assertEqual(len(calls),4)

if __name__=='__main__':unittest.main(verbosity=2)
