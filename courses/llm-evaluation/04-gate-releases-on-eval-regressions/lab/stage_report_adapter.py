"""Normalize saved docs-stage metrics for gate.py; this does not run pytest or a judge."""
import argparse,hashlib,json,math
from pathlib import Path
from gate import gate,EXIT
METRICS=('faithfulness','contextual_recall','answer_relevancy')
POLICY={'max_regressions':0,'min_pass_rate':0.9,'critical':['test_tools','test_faithfulness']}
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def score(value):
 if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('invalid_score')
 return value

def adapt(report):
 key=report['key'];threshold=score(report['threshold'])
 required=('cases','cases_sha','docs_sha','prompt_sha','model','embedder','judge')
 if any(not isinstance(key.get(k),str) or not key[k] for k in required):raise ValueError('missing_report_key')
 if type(key.get('strict_faithfulness')) is not bool or type(report['k']) is not int or report['k']<1 or key['k']!=report['k']:raise ValueError('invalid_contract')
 rows=report['rows']
 if not isinstance(rows,list) or not rows:raise ValueError('empty_cases')
 tests=[];applicability={};seen=set()
 for row in rows:
  case=row['id']
  if not isinstance(case,str) or not case or '::' in case or case in seen:raise ValueError('invalid_or_duplicate_case')
  seen.add(case);checks={};tools=row['tools'];s=score(tools['score'])
  if type(tools['pass']) is not bool or not isinstance(tools['unexpected'],list) or tools['pass']!=(s>=threshold and not tools['unexpected']):raise ValueError('inconsistent_tools')
  checks['tools']=tools['pass'];retrieval=row['retrieval']
  if retrieval is not None:
   if type(retrieval['hit']) is not bool:raise ValueError('invalid_retrieval')
   score(retrieval['reciprocal_rank']);checks['retrieval']=score(retrieval['recall'])>=threshold
  judged=row['judged']
  if not isinstance(judged,dict) or 'answer_relevancy' not in judged:raise ValueError('missing_answer_metric')
  for name,metric in judged.items():
   if name not in (*METRICS,'contextual_precision') or not isinstance(metric,dict) or not isinstance(metric.get('reason'),str):raise ValueError('invalid_judged_metric')
   score(metric['score'])
  # Source contract: no source context on the thanks case. Every other case has source metrics.
  expected={'answer_relevancy'} if case=='thanks' else {*METRICS,'contextual_precision'}
  if set(judged)!=expected:raise ValueError('missing_or_unexpected_metric')
  for name in METRICS:
   if name in judged:checks[name]=judged[name]['score']>=threshold
  first=next((name for name in ('tools','retrieval',*METRICS) if name in checks and not checks[name]),None)
  if first!=row['first_failure']:raise ValueError('inconsistent_first_failure')
  applicability[case]=sorted(checks)
  for name,passed in checks.items():tests.append({'nodeid':f'docs-stages::{case}::test_{name}','outcome':'passed' if passed else 'failed'})
 contract={k:key[k] for k in ('cases','cases_sha','docs_sha','embedder','k','strict_faithfulness')}
 contract.update({'threshold':threshold,'protocol':'docs-stage-scores-v1','applicability':applicability})
 return {'eval':{'dataset':key['cases'],'dataset_sha':digest(contract),'judge_model':key['judge'],'model':key['model'],'prompt_version':'sha:'+key['prompt_sha'],'prompt_sha':key['prompt_sha']},'tests':tests,'contract':contract,'provenance':{'source_report_sha256':digest(report),'execution_mode':'offline-metric-to-outcome-adapter','prompt_version_is_derived':True,'source_metrics':rows}}

def compare(baseline,candidate):
 return gate(adapt(baseline),adapt(candidate),POLICY)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 if a.out.exists():raise SystemExit('Refusing to overwrite a result')
 b=json.loads(a.baseline.read_text());c=json.loads(a.candidate.read_text());result={'execution_mode':'offline-saved-stage-report-adaptation','policy':POLICY,'baseline':adapt(b),'candidate':adapt(c),'decision':compare(b,c)}
 a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['decision']));raise SystemExit(EXIT[result['decision']['decision']])
