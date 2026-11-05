"""Record a RAG baseline. Default is an offline plan, never model execution."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from baseline_lib import (ROOT,CONFIG,MODEL_DIGESTS,Reply,PipelineSystem,annotate,build_index,chunks,code_bundle_sha,
 digest,harness,human_template,index_identity,load_frozen,plan,read,sha,source_hashes,write)


def record_once(out,runplan,models,guard,*,mode):
 cases,_,manifest=load_frozen()
 selected=harness.plan(cases,runplan['splits'],1,runplan['include_held_out'])
 prepared=chunks();texts=[d.page_content for d in prepared]
 start=time.monotonic();document_vectors=models.documents(texts)
 if len(document_vectors)!=len(texts):raise ValueError('Four document embeddings required')
 vectors={'documents':dict(zip(texts,document_vectors,strict=True)),'questions':{}}
 build_start=time.monotonic();index=build_index(vectors);identity=index_identity(vectors,models.models,manifest)
 index_seconds=time.monotonic()-build_start
 observations={}
 def persist():write(out/'case-observations.json',observations)
 system=PipelineSystem(index,models,identity,observations,persist,query_backend=models,query_vectors=vectors['questions'])
 system.mode=mode
 import baseline_task
 task=harness.load_task('baseline_task')
 recording=harness.record(system,cases,runplan['splits'],trials=1,include_held_out=runplan['include_held_out'])
 write(out/'recording.json',recording);persist();write(out/'vectors.json',vectors)
 # Always evaluate saved responses, not the live system a second time.
 replay=harness.ReplaySystem(out/'recording.json',cases)
 report=harness.run(replay,cases,task,runplan['splits'],trials=1,include_held_out=runplan['include_held_out'])
 write(out/'automatic-contracts.json',report)
 metrics=annotate(recording,observations,cases);write(out/'measurements.json',metrics)
 write(out/'human-review.json',human_template(cases,recording))
 names=['recording.json','case-observations.json','vectors.json','automatic-contracts.json','measurements.json','human-review.json']
 binding={'created_at_utc':datetime.now(timezone.utc).isoformat(),'plan':runplan,'execution_mode':mode,
  'source_hashes':source_hashes(),'artifacts':{n:sha((out/n).read_bytes())for n in names},
  'index_identity':identity,'document_embedding_seconds':build_start-start,
  'index_build_seconds':index_seconds,
  'human_semantics':'unreviewed; automatic passes are not factual accuracy',
  'observed_counts':guard.counts,'budget':'No retry/repair/judge. One trial; public teaching split, not unseen benchmark.'}
 write(out/'run-manifest.json',binding)
 return binding


def replay(out):
 binding=read(out/'run-manifest.json')
 if binding['source_hashes']!=source_hashes():raise ValueError('Current source differs from the recorded baseline')
 if binding['plan']['code_bundle_sha256']!=code_bundle_sha():raise ValueError('Code/config/rubric binding changed')
 # human-review.json is an initial template and is immutable here. Record completed reviews in a separate bound file.
 for name,h in binding['artifacts'].items():
  if sha((out/name).read_bytes())!=h:raise ValueError('Recorded artifact changed: '+name)
 cases,_,_=load_frozen();runplan=binding['plan'];task=harness.load_task('baseline_task')
 saved=harness.ReplaySystem(out/'recording.json',cases)
 report=harness.run(saved,cases,task,runplan['splits'],trials=1,include_held_out=runplan['include_held_out'])
 metrics=annotate(read(out/'recording.json'),read(out/'case-observations.json'),cases)
 return {'automatic_contracts':report,'measurements':metrics,'mode':'exact saved replay; no model calls','human_semantics':'unreviewed'}


def child_record(out,runplan):
 # Parent supplies a clean allowlist, never inherited provider variables/credentials.
 if os.environ.get('AIML_BASELINE_ISOLATED_CHILD')!='1' or any(os.environ.get(k)for k in
  ('GOOGLE_API_KEY','GEMINI_API_KEY','OPENAI_API_KEY','GOOGLE_APPLICATION_CREDENTIALS','ANTHROPIC_API_KEY')):
  raise ValueError('Fresh mode requires the isolated clean child')
 if code_bundle_sha()!=runplan['code_bundle_sha256']:raise ValueError('Reviewed source changed before model access')
 from local_models import CallGuard,FreshModels
 guard=CallGuard(runplan,[d.page_content for d in chunks()])
 def ledger():write(out/'http-ledger.json',{'counts':guard.counts,'http':guard.http,'network':guard.network})
 guard.save=ledger;ledger()
 try:
  with guard.installed():
   models=FreshModels(guard)
   result=record_once(out,runplan,models,guard,mode='fresh_local_inference')
  print(json.dumps({'status':'recorded; human semantic review pending','observed_counts':result['observed_counts']}))
 except Exception:
  write(out/'failure.json',{'at_utc':datetime.now(timezone.utc).isoformat(),'traceback':traceback.format_exc(),'counts':guard.counts,
   'meaning':'Retained failed attempt. No automatic retry or claim of a complete baseline.'})
  raise
 finally:ledger()


def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('action',choices=['plan','record','replay'],nargs='?',default='plan')
 p.add_argument('--split',action='append',choices=['development','held_out'])
 p.add_argument('--include-held-out',action='store_true');p.add_argument('--trials',type=int,default=1)
 p.add_argument('--out',type=Path);p.add_argument('--record',type=Path)
 p.add_argument('--fresh-local',action='store_true')
 p.add_argument('--reviewed-code-sha256',help='Operator binds the exact code reviewed by root; this hash is not authentication/permission.')
 args=p.parse_args(argv)
 if args.trials!=1:raise ValueError('Only one trial is in scope')
 if args.action=='replay':
  if not args.record or args.fresh_local:raise ValueError('Replay needs --record and never --fresh-local')
  print(json.dumps(replay(args.record),indent=2));return 0
 runplan=plan(args.split or ['development'],args.include_held_out)
 if args.action=='plan':
  if args.fresh_local:raise ValueError('Plan remains offline; record is a separate explicit action')
  print(json.dumps(runplan,indent=2));return 0
 if not args.fresh_local or args.reviewed_code_sha256!=runplan['code_bundle_sha256']:
  raise ValueError('No inference: root must review exact source, then the operator supplies --fresh-local and that reviewed code hash')
 if not args.out:raise ValueError('Use a new dated --out folder; existing runs are never overwritten')
 out=args.out.resolve()
 if out.is_relative_to(ROOT) and not out.is_relative_to(ROOT/'runs'):raise ValueError('Outputs inside the lab belong under runs/')
 out.mkdir(parents=True,exist_ok=False);(out/'isolated-home').mkdir()
 write(out/'run-plan.json',runplan)
 env={'PATH':str(Path(sys.executable).parent)+':/usr/bin:/bin','HOME':str(out/'isolated-home'),'TMPDIR':'/tmp',
  'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','AIML_BASELINE_ISOLATED_CHILD':'1',
  'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','OTEL_SDK_DISABLED':'true','DO_NOT_TRACK':'1',
  'LITELLM_LOCAL_MODEL_COST_MAP':'True','LITELLM_TELEMETRY':'False','DEEPEVAL_TELEMETRY_OPT_OUT':'1'}
 command=[sys.executable,str(ROOT/'baseline.py'),'--internal-child',str(out)]
 launch={'command':command,'cwd':str(ROOT),'child_environment':env,'provider_credentials_inherited':False,
  'at_utc':datetime.now(timezone.utc).isoformat(),'reviewed_code_sha256':args.reviewed_code_sha256,'packages':{k:importlib.metadata.version(k)for k in ['langchain-core','langchain-ollama','langchain-text-splitters','ollama','pydantic','numpy']}}
 write(out/'launch.json',launch)
 try:
  with (out/'stdout.txt').open('w')as stdout,(out/'stderr.txt').open('w')as stderr:
   done=subprocess.run(command,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,timeout=1200)
  launch['exit_code']=done.returncode
 except subprocess.TimeoutExpired:launch['exit_code']=124
 write(out/'launch.json',launch);print(json.dumps({'out':str(out),'exit_code':launch['exit_code'],'no_automatic_retry':True}))
 return launch['exit_code']


if __name__=='__main__':
 if len(sys.argv)==3 and sys.argv[1]=='--internal-child':
  target=Path(sys.argv[2]);child_record(target,read(target/'run-plan.json'))
 else:
  try:raise SystemExit(main())
  except Exception as exc:print(type(exc).__name__+': '+str(exc),file=sys.stderr);raise SystemExit(2)
