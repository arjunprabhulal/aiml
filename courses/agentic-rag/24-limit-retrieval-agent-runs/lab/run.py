"""Actual offline scripted-policy runs with admission limits and controlled faults."""
import argparse
import json
from pathlib import Path
from tools import DocumentationTools,load_snapshot
from refine import ScriptedPolicy
from limits import Limits,run_limited

QUESTION='Will write_text replace the contents of an existing file?'


class ControlledFaultTools(DocumentationTools):
    def search(self,**arguments):
        super().search(**arguments)
        raise RuntimeError('controlled_after_search_fault')


def run():
    snapshot=load_snapshot();cases=[]
    configurations=[('within_limits',Limits()),('step_limit',Limits(max_steps=2)),('search_limit',Limits(max_searches=1)),('read_limit',Limits(max_reads=1)),('source_byte_limit',Limits(max_source_bytes=200))]
    for name,limits in configurations:
        tools=DocumentationTools(snapshot);policy=ScriptedPolicy(QUESTION,'3.12')
        try:result=run_limited(tools,policy,limits)
        finally:tools.close()
        cases.append({'case_id':name,'policy_terminal_status':policy.terminal_status,'policy_reason':policy.reason,'result':result})
    tools=ControlledFaultTools(snapshot);policy=ScriptedPolicy(QUESTION,'3.12')
    try:fault=run_limited(tools,policy)
    finally:tools.close()
    return {'execution_mode':'offline-scripted-controller-limits','model_called':False,'corpus_id':snapshot['snapshot_id'],'question':QUESTION,'version':'3.12','cases':cases,'controlled_tool_failure':{'scope':'deliberate fault after actual local search; not a reliability measurement','result':fault},'limit':'Counts cover admitted tool attempts and validated read-text bytes. Corpus initialization, policy callback computation, wall time, model tokens and inference costs are outside this contract. No model agent or generated answer.'}


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
