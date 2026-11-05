"""RAG-specific wiring and measurements; the runner and pipeline are reused."""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'vendor/evals'))
import harness
from retrieval_scores import retrieval_scores
import rag_dataset
from agentic_rag.concepts import Reply, SavedEmbeddings, build_index, chunks
from agentic_rag.request_trace import digest, chunk_id, trace_request

DATASET_SHA='1603dde3e9e4d3fbafb14126e5c002584c6f945c29968488b01406618a6035b9'
EMBED='qwen3-embedding:0.6b'
MODEL='gemma4:e2b'
MODEL_DIGESTS={EMBED:'ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d',
 MODEL:'b37049369adfe3d2b653af0ab301a062ca5cbe96ace6aa0d3f2559ee9b563fc2'}
QUERY_INSTRUCTION='Retrieve Python documentation that answers the developer question'
CONFIG={'embedding_model':EMBED,'answer_model':MODEL,'query_instruction':QUERY_INSTRUCTION,
 'k':2,'splitter':{'name':'RecursiveCharacterTextSplitter','chunk_size':280,'chunk_overlap':40},
 'temperature':0,'num_predict':400,'structured_output_method':'json_schema','trials':1,
 'embedding_http_timeout_seconds':120,'generation_http_timeout_seconds':180,'whole_child_timeout_seconds':1200,
 'automatic_retries':0,'judge_calls':0}


def sha(data):return hashlib.sha256(data).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def write(path,value):
 path=Path(path);tmp=path.with_name(path.name+'.tmp')
 tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n');tmp.replace(path)


def source_files():
 return sorted(p for p in ROOT.rglob('*') if p.is_file() and not any(x in p.relative_to(ROOT).parts for x in ('runs','__pycache__','.venv'))
               and (p.suffix in ('.py','.json','.toml') or p.name in ('requirements.txt','requirements-lock.txt','README.md','LICENSE')))


def source_hashes():return {str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in source_files()}
def code_bundle_sha():return digest(source_hashes())


def verify_reuse():
 refs=read(ROOT/'baseline-source-versions.json')['reuse']
 for rel,ref in refs.items():
  path=ROOT/rel
  if ref.get('unchanged') and sha(path.read_bytes())!=ref['sha256']:
   raise ValueError('Reused file changed: '+rel)
  if ref.get('function_unchanged'):
   text=path.read_text();node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='retrieval_scores')
   if sha(ast.get_source_segment(text,node).encode())!=ref['function_sha256']:raise ValueError('Reused retrieval metric changed')
 if (ROOT/'data/docs.json').read_bytes()!=(ROOT/'data/sources.json').read_bytes():
  raise ValueError('Pipeline corpus and frozen dataset sources differ')
 return {'unchanged_reuse_files':sum(r.get('unchanged',False) for r in refs.values()),'metric_function_unchanged':True}


def load_frozen():
 verify_reuse()
 cases=rag_dataset.load_questions()
 sources,passages,manifest=rag_dataset.load_sources()
 lock=read(ROOT/'data/held-out.lock.json')
 checked=rag_dataset.validate_dataset(cases,sources,passages,lock)
 if cases['sha256']!=DATASET_SHA:raise ValueError('The approved eight-case dataset changed')
 if checked['counts']!={'cases':8,'sources':4,'passages':4,'by_split':{'development':4,'held_out':4},'by_class':{'answerable':3,'unsupported':3,'version_specific':2}}:
  raise ValueError('Approved dataset counts changed')
 if [chunk_id(d) for d in chunks()]!=[chunk_id(d) for d in passages]:raise ValueError('Existing pipeline chunks differ from dataset targets')
 return cases,sources,manifest


def plan(splits=('development',),include_held_out=False):
 cases,sources,manifest=load_frozen()
 selected=harness.plan(cases,list(splits),1,include_held_out)
 return {'mode':'plan_only_no_model_call','case_ids':[c['id'] for c in selected],
  'splits':sorted(set(splits)),'include_held_out':include_held_out,'trials':1,'config':CONFIG,
  'case_set_sha256':cases['sha256'],'corpus_canonical_sha256':manifest['sources_sha256'],
  'rubric_sha256':sha((ROOT/'frozen-rubric.json').read_bytes()),'code_bundle_sha256':code_bundle_sha(),
  'model_digests':MODEL_DIGESTS,'max_document_embedding_calls':1,'max_query_embedding_calls':len(selected),
  'max_generation_calls':len(selected),'max_inference_http_calls':1+2*len(selected),
  'requested_generation_token_ceiling':400*len(selected),'max_metadata_calls':3,
  'teaching_split':'Public4development/4held_out fixtures; not unseen external data.',
  'root_review_required_before_inference':True}


def query_text(question):return 'Instruct: '+QUERY_INSTRUCTION+'\nQuery: '+question


def index_identity(vectors,models,manifest):
 prepared=chunks()
 if set(vectors['documents'])!={d.page_content for d in prepared}:raise ValueError('Fresh corpus vectors do not match all four passages')
 descriptor={'corpus_canonical_sha256':manifest['sources_sha256'],'pipeline_corpus_file_sha256':sha((ROOT/'data/docs.json').read_bytes()),
  'embedding_model':models[EMBED],'splitter':CONFIG['splitter'],'chunk_ids':[chunk_id(d) for d in prepared],
  'vectors_sha256':digest(vectors['documents'])}
 return {'corpus_sha256':sha((ROOT/'data/docs.json').read_bytes()),'logical_index_id':digest(descriptor),
  'index_descriptor':descriptor,'model_digests':models}


class PipelineSystem:
 """Pass only case.input into the unchanged pipeline, never labels or tags."""
 mode='fresh_local_inference'
 name='fixed-python-docs-rag'
 version='1'
 tools=None
 def __init__(self,index,generator,identity,observations,persist=lambda:None,query_backend=None,query_vectors=None):
  self.index_object,self.generator,self.identity=index,generator,identity
  self.mode=generator.mode
  self.observations,self.persist=observations,persist
  self.query_backend,self.query_vectors=query_backend,query_vectors
  self.model=digest({'model_digests':identity['model_digests'],'options':CONFIG})
  self.prompt=digest({'prompt_source':sha((ROOT/'src/agentic_rag/concepts.py').read_bytes()),'schema':Reply.model_json_schema()})
  self.index=identity['logical_index_id']
 def respond(self,case,trial):
  if trial!=0:raise ValueError('Only one trial per case is approved')
  if case['id'] in self.observations:raise ValueError('Case already attempted; no retry')
  events=[];row={'case_id':case['id'],'question':case['input'],'mode':self.mode,'events':events}
  self.observations[case['id']]=row;self.persist()
  class Adapter:
   mode='fresh local Ollama inference'
   def generate(_,question,messages):
    row['messages']=json.loads(json.dumps(messages));row['request_sha256']=digest(messages)
    result=self.generator.generate(case['id'],question,messages)
    row['generation']=result;self.persist()
    if result.get('parsing_error') or result.get('parsed') is None:
     raise ValueError('Structured reply could not be parsed; raw reply retained, no repair')
    return result['parsed']
  try:
   if self.query_backend is not None:
    self.query_vectors[case['input']]=self.query_backend.query(case['id'],case['input'])
   trace=trace_request(case['input'],self.index_object,Adapter(),self.identity,events=events)
   row['result']=trace['result']
   return harness.Answer(trace['result'],{'trace':trace,'request_sha256':row.get('request_sha256'),
    'raw_message':row.get('generation',{}).get('raw'),'mode':self.mode})
  except Exception as exc:
   row['error']={'type':type(exc).__name__,'message':str(exc)}
   raise
  finally:self.persist()


def annotate(recording,observations,cases):
 """Separate retrieval measurements and missing/error outcomes; no semantic score."""
 rows=[]
 for case in cases['cases']:
  if case['id'] not in recording['responses']:continue
  trials=recording['responses'][case['id']]
  if len(trials)!=1:raise ValueError('One recorded trial required')
  trial=trials[0];obs=observations.get(case['id'])
  if obs is None or obs.get('question')!=case['input']:raise ValueError('Missing/exact-question observation mismatch')
  retrieved=next((e['candidates'] for e in obs['events'] if e['kind']=='retrieval_completed'),None)
  expected=[t['chunk_id'] for t in case['expected']['targets']]
  metric=None if retrieved is None else retrieval_scores([r['chunk_id'] for r in retrieved],expected)
  output=trial.get('output')
  status_match=None if output is None else output.get('status')==case['expected']['status']
  target_alignment=None if output is None or not expected else bool({t['source_id']for t in case['expected']['targets']}&set(output.get('source_ids',[])))
  rows.append({'case_id':case['id'],'split':case['split'],'class':case['class'],
   'retrieved_chunk_ids':None if retrieved is None else[r['chunk_id']for r in retrieved],
   'annotated_target_chunk_ids':expected,'retrieval':metric,
   'reply_status':None if output is None else output.get('status'),'expected_status':case['expected']['status'],
   'status_matches_annotation':status_match,'target_source_alignment':target_alignment,
   'error':trial.get('error'),'automatic_contracts_are_not_faithfulness':True,
   'human_semantic_verdict':'unreviewed','human_review_required':True,
   'usage_metadata':obs.get('generation',{}).get('raw',{}).get('usage_metadata'),
   'response_metadata':obs.get('generation',{}).get('raw',{}).get('response_metadata'),
   'latency_seconds':trial['latency_s'],'latency_scope':'one whole query including fresh query embedding when the fresh adapter is used; one-off document embedding/index build separate'})
 summary={}
 for split in sorted({r['split']for r in rows}):
  group=[r for r in rows if r['split']==split]
  supported=[r for r in group if r['annotated_target_chunk_ids']]
  measured=[r for r in supported if r['retrieval'] is not None]
  unsupported=[r for r in group if not r['annotated_target_chunk_ids']]
  summary[split]={'cases':len(group),'supported':len(supported),'unsupported':len(unsupported),
   'retrieval_measurements':len(measured),'retrieval_unmeasured_errors':len(supported)-len(measured),
   'target_hits_at_2':sum(r['retrieval']['hit']for r in measured),
   'mean_target_reciprocal_rank_at_2':None if not measured else sum(r['retrieval']['reciprocal_rank']for r in measured)/len(measured),
   'status_matches':sum(r['status_matches_annotation']is True for r in group),
   'false_answer_on_unsupported':sum(r['reply_status']=='answered'for r in unsupported),
   'false_abstention_on_supported':sum(r['reply_status']=='not_in_docs'for r in supported),
   'missing_or_error_outputs':sum(r['reply_status']is None for r in group),
   'human_semantics_reviewed':0,'scope':'One trial per public teaching case, not a general accuracy estimate.'}
 return {'rows':rows,'by_split':summary,'retrieval_null_rule':'Unsupported or unmeasured error→null, never perfect.',
  'metric_note':'One annotated target per supported case:recall@2equalsHit@2; these are not independent measurements.'}


def human_template(cases,recording):
 rubric=read(ROOT/'frozen-rubric.json')
 return {'rubric_sha256':sha((ROOT/'frozen-rubric.json').read_bytes()),'verdicts':['pass','fail','needs_review'],
  'cases':{c['id']:{'answer_sha256':digest(recording['responses'][c['id']][0].get('output')),
   'criteria':rubric['cases'][c['id']],'verdict':'unreviewed','reviewer':None,'supporting_or_contradicting_passage':None,'notes':None}
   for c in cases['cases']if c['id']in recording['responses']},
  'note':'Automatic checks never fill this human semantic review.'}
