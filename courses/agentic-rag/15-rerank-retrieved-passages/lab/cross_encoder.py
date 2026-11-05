"""Pinned query/passage cross-encoder: acquire separately, infer locally."""
import argparse,hashlib,json,math,time,urllib.request
from pathlib import Path
from rerank import rerank
MODEL='cross-encoder/ms-marco-MiniLM-L6-v2'
REVISION='233902d25c440f23af6f7d6e94d2946bac0bee0a'
FILES=('config.json','model.safetensors','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt')
def manifest(directory):return {n:hashlib.sha256((Path(directory)/n).read_bytes()).hexdigest() for n in FILES}
def prepare(directory):
 directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
 for name in FILES:
  if not (directory/name).exists():
   with urllib.request.urlopen(f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}',timeout=180) as response:(directory/name).write_bytes(response.read())
 result={'model':MODEL,'revision':REVISION,'license':'Apache-2.0','files':manifest(directory)}
 (directory/'acquisition.json').write_text(json.dumps(result,indent=2)+'\n');return result

def accept_scores(question,candidates,snapshot,scores):
 rerank(question,candidates,snapshot,k=max(1,len(candidates)))
 if len(scores)!=len(candidates) or any(type(x) not in (int,float) or not math.isfinite(x) for x in scores):raise ValueError('invalid_cross_encoder_scores')
 rows=[{**r,'incoming_rank':i,'cross_encoder_logit':s} for i,(r,s) in enumerate(zip(candidates,scores),1)]
 rows.sort(key=lambda r:(-r['cross_encoder_logit'],r['incoming_rank']))
 return [{**r,'cross_encoder_rank':i} for i,r in enumerate(rows,1)]
class CrossEncoder:
 def __init__(self,directory):
  import torch,transformers
  from transformers import AutoTokenizer,AutoModelForSequenceClassification
  torch.set_num_threads(1);torch.manual_seed(0);self.torch=torch
  self.environment={'torch':torch.__version__,'transformers':transformers.__version__,'device':'cpu','dtype':'float32','threads':1}
  self.acquisition=json.loads((Path(directory)/'acquisition.json').read_text())
  if self.acquisition['model']!=MODEL or self.acquisition['revision']!=REVISION or self.acquisition['files']!=manifest(directory):raise ValueError('model_manifest_mismatch')
  self.tokenizer=AutoTokenizer.from_pretrained(directory,local_files_only=True,trust_remote_code=False)
  self.model=AutoModelForSequenceClassification.from_pretrained(directory,local_files_only=True,trust_remote_code=False,use_safetensors=True).float().eval()
 def scores(self,q,rows):
  if not rows:return [],0.0
  tokens=self.tokenizer([q]*len(rows),[r['text'] for r in rows],padding=True,truncation=False,return_tensors='pt')
  if tokens['input_ids'].shape[1]>512:raise ValueError('pair_exceeds_model_context')
  start=time.perf_counter()
  with self.torch.inference_mode():scores=self.model(**tokens).logits.reshape(-1).tolist()
  return scores,time.perf_counter()-start

def run(directory):
 root=Path(__file__).parent;snapshot=json.loads((root/'fixtures/snapshot.json').read_text());encoder=CrossEncoder(directory)
 original=json.loads((root/'runs/2026-10-23-rerank/result.json').read_text());rows=[]
 for c in original['development_cases']:
  scores,elapsed=encoder.scores(c['query'],c['before'])
  rows.append({'case_id':c['case_id'],'question':c['query'],'candidates':c['before'],'coverage':c['after'],'scores_in_candidate_order':scores,'cross_encoder':accept_scores(c['query'],c['before'],snapshot,scores),'inference_seconds':elapsed})
 raw=(root/'fixtures/expanded-cases.json').read_bytes();cases=json.loads(raw);expanded=[]
 for c in cases:
  candidates=[{'chunk_id':ch['chunk_id'],'source_id':s['source_id'],'version':s['version'],'url':s['url'],'text':ch['text']} for s in snapshot['documents'] if s['version']==c['version'] for ch in s['chunks']]
  scores,elapsed=encoder.scores(c['question'],candidates);coverage=rerank(c['question'],candidates,snapshot,k=max(1,len(candidates)));ranked=accept_scores(c['question'],candidates,snapshot,scores)
  targets=set(c['target_sources'])
  def outcome(order):
   if not targets:return {'top1_hit':None,'reason':'no_supported_target'}
   return {'top1_hit':bool(order and order[0]['source_id'] in targets),'reciprocal_rank':next((1/i for i,r in enumerate(order,1) if r['source_id'] in targets),0)}
  expanded.append({**c,'candidates':candidates,'coverage':coverage,'scores_in_candidate_order':scores,'cross_encoder':ranked,'inference_seconds':elapsed,'outcome':{'coverage':outcome(coverage),'cross_encoder':outcome(ranked)}})
 summary={}
 for split in ('diagnostic','validation'):
  summary[split]={}
  for scorer in ('coverage','cross_encoder'):
   eligible=[r['outcome'][scorer] for r in expanded if r['split']==split and r['outcome'][scorer]['top1_hit'] is not None]
   summary[split][scorer]={'answerable':len(eligible),'top1_hits':sum(r['top1_hit'] for r in eligible),'mrr':sum(r['reciprocal_rank'] for r in eligible)/len(eligible) if eligible else None}
 return {'execution_mode':'fresh-local-cross-encoder-inference','model':encoder.acquisition,'environment':encoder.environment,'cases_sha256':hashlib.sha256(raw).hexdigest(),'snapshot_id':snapshot['snapshot_id'],'original_candidate_comparison':rows,'expanded_cases':expanded,'summary':summary,'scope':'Raw logits are not calibrated probabilities. Original hybrid candidates are unchanged. Expanded cases use all version-eligible passages in a four-document fixture; diagnostic and validation questions remain separate. This does not establish general retrieval quality, answer truth or support for unsupported questions.'}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--model-dir',required=True);p.add_argument('--prepare',action='store_true');p.add_argument('--output',type=Path);a=p.parse_args()
 if a.prepare:print(json.dumps(prepare(a.model_dir)))
 else:
  if not a.output or a.output.exists():raise SystemExit('Choose a new output path')
  result=run(a.model_dir);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['summary']))
