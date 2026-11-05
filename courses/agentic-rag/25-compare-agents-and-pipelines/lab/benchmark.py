"""Broader frozen comparison; historical questions and new validation strata stay separate."""
import argparse
import hashlib
import json
from pathlib import Path
from gemini_client import Gemini,MODEL
from gemini_policy import bind_labels,LIMITS
from schema_policy import SchemaPolicy
from compare import FixedPipeline,check_outcome
from refine import ScriptedPolicy
from tools import DocumentationTools,load_snapshot
from limits import run_limited

POLICIES=('fixed_pipeline','scripted_refinement','gemini_schema_v2')

def summary(trials,cases):
    strata={c['case_id']:c['split'] for c in cases};result={}
    for split in ('diagnostic','validation'):
        result[split]={}
        for policy in POLICIES:
            rows=[r for r in trials if r['policy']==policy and strata[r['case_id']]==split]
            result[split][policy]={'cases':len(rows),**{s:sum(r['outcome_check']['status']==s for r in rows) for s in ('pass','fail','incomplete')},'tool_actions':sum(r['runtime']['usage']['steps'] for r in rows),'model_calls':sum(r['model_calls'] for r in rows),'refused_proposals':sum(e['decision']=='refused' for r in rows for e in r['runtime']['trace']),'admission_denials':sum(e['decision']=='denied' for r in rows for e in r['runtime']['trace'])}
    return result

def run(client):
    root=Path(__file__).parent;raw=(root/'fixtures/expanded-cases.json').read_bytes();cases=json.loads(raw);snapshot=load_snapshot();trials=[]
    for c in cases:
        # Remove split, stratum and target labels before policy execution.
        question={k:c[k] for k in ('case_id','question','version')}
        for name in POLICIES:
            tools=DocumentationTools(snapshot)
            policy=(SchemaPolicy(question['question'],question['version'],client) if name=='gemini_schema_v2' else (FixedPipeline if name=='fixed_pipeline' else ScriptedPolicy)(question['question'],question['version']))
            try:runtime=run_limited(tools,policy,LIMITS)
            finally:tools.close()
            runtime['scope']='Host validates bounded documentation actions; policy inference and request receipts are recorded separately.'
            trials.append({**question,'policy':name,'policy_terminal_status':policy.terminal_status,'policy_reason':policy.reason,'runtime':runtime,'model_calls':getattr(policy,'calls',0),'proposals':getattr(policy,'proposals',[])})
    labels=bind_labels(snapshot,cases)
    for trial in trials:trial['outcome_check']=check_outcome(trial,labels[trial['case_id']])
    return {'execution_mode':'fresh-gemini-schema-policy-comparison','model':MODEL,'cases_sha256':hashlib.sha256(raw).hexdigest(),'snapshot_id':snapshot['snapshot_id'],'cases':cases,'trials':trials,'summary':summary(trials,cases),'calls':client.calls,
            'limits':'Four previously observed questions are diagnostic; eight new strings were frozen before v2 execution. Same tiny corpus and related intent families, not an independent quality benchmark. Compare action validity and exact target reads; unsupported cases remain incomplete. Structured decisions are not provider function calls. V1 records are retained unchanged.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--ledger',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise SystemExit('Refusing to overwrite a run')
    client=Gemini(a.ledger,a.output.parent/'requests');result=run(client)
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['summary']))
