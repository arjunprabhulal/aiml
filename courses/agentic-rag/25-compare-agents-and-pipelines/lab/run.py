"""Execute both scripted policies first, then bind labels and check source outcomes."""
import argparse
import json
from pathlib import Path
from tools import load_snapshot
from compare import execute,bind_targets,evaluate,SHARED_LIMITS
from dataclasses import asdict


def run():
    root=Path(__file__).parent;snapshot=load_snapshot();cases=json.loads((root/'fixtures/development-cases.json').read_text())
    questions=[{'case_id':case['id'],'question':case['input'],'version':case['tags']['python_version']} for case in cases]
    trials=execute(snapshot,questions)
    labels,receipts=bind_targets(snapshot,cases)
    checked,summary=evaluate(trials,labels)
    return {'execution_mode':'offline-scripted-policy-versus-fixed-pipeline','model_called':False,'corpus_id':snapshot['snapshot_id'],'configuration':{'shared_limits':asdict(SHARED_LIMITS),'initial_query':'text','search_k':2,'fixed_pipeline':'one search and first read; no feedback branch','scripted_refinement':'question-only hand-coded rules plus read-marker feedback; at most two rounds','scope':'four original development questions only; no held-out queries or parameter tuning'},'target_binding_receipts':receipts,'trials':checked,'summary':summary,'confounds':['The scripted policy contains additional domain-specific rewrite and marker rules.','Both have the same maximum budget, but the fixed pipeline usually uses fewer actions.','This comparison does not isolate architecture from rule design or actual tool effort.'],'limit':'Deterministic checks report whether exact bound target passages were read, not generated-answer quality or semantic understanding. Unsupported cases have no retrieval target and remain incomplete. Tiny development fixtures do not establish general quality.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=run()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        summary={'execution_mode':result['execution_mode'],'model_called':result['model_called']}
        if 'cases' in result:summary['cases']={case['case_id']:case['result']['controller_status'] for case in result['cases']}
        else:summary['outcomes']=result['summary']
        print(json.dumps(summary,sort_keys=True))
    else:print(json.dumps(result,indent=2))
