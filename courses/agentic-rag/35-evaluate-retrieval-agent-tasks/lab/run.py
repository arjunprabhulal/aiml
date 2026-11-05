"""Run deterministic development fixture checks; no model or external service."""
import argparse,copy,json
from pathlib import Path
from evaluator import DEFAULT_CONFIG,execute_trials,evaluate_run,release_gate
from tools import load_snapshot,DocumentationTools
from limits import Limits,run_limited
from refine import ScriptedPolicy

def run():
    snapshot=load_snapshot();cases=json.loads((Path(__file__).parent/'fixtures/development-cases.json').read_text())
    questions=[{'case_id':c['id'],'question':c['input'],'version':c['tags']['python_version']} for c in cases]
    config=copy.deepcopy(DEFAULT_CONFIG)
    trials=execute_trials(snapshot,questions,config)
    normal=evaluate_run(snapshot,cases,trials,config)
    gates={p:release_gate(normal,normal['identity'],p) for p in config['policies']}
    limited_config=copy.deepcopy(config);limited_config['limits']['max_steps']=1
    limited_trials=execute_trials(snapshot,questions,limited_config)
    limited=evaluate_run(snapshot,cases,limited_trials,limited_config)
    # A checker fault fixture: modify actual completed read results after execution.
    corrupted=copy.deepcopy(trials);corrupt_ids=[]
    target=next(c['id'] for c in cases if c['class']=='answerable')
    for trial in corrupted:
        if trial['case_id']!=target or trial['policy']!='scripted_refinement':continue
        row=next(o for o in trial['runtime']['observations'] if o['tool']=='read');row['result']['text']='corrupted after execution'
        event=next(e for e in trial['runtime']['trace'] if e.get('action',{}).get('tool')=='read')
        event['result']=copy.deepcopy(row['result'])
        corrupt_ids.append(trial['trial_id'])
    corrupt_report=evaluate_run(snapshot,cases,corrupted,config)
    # Actual core tool failure, not a fabricated successful trace.
    class BrokenTools(DocumentationTools):
        def search(self,**kwargs):raise RuntimeError('controlled_tool_failure')
    failed=copy.deepcopy(trials)
    for t in failed:
        if t['case_id']!=target or t['policy']!='scripted_refinement':continue
        tools=BrokenTools(snapshot);policy=ScriptedPolicy(t['question'],t['version'])
        try:t['runtime']=run_limited(tools,policy,Limits(**config['limits']))
        finally:tools.close()
        t['policy_terminal_status']=policy.terminal_status;t['policy_reason']=policy.reason
    failed_report=evaluate_run(snapshot,cases,failed,config)
    missing=copy.deepcopy(cases);next(c for c in missing if c['class']=='answerable')['expected']['targets'][0]['chunk_text_sha256']='0'*64
    try:evaluate_run(snapshot,missing,trials,config);raise AssertionError('expected_missing_binding')
    except ValueError as error:missing_result={'status':'NOTCOMPARABLE','reason':str(error),'execution_completed_before_label_binding':True,'executed_trial_ids':[t['trial_id'] for t in trials]}
    return {'schema_version':1,'execution_mode':'offline-deterministic-scripted-retrieval-task-evaluation','model_called':False,'configuration_frozen_before_execution':config,'normal':normal,'release_gates':gates,'step_budget':{'report':limited,'gate':release_gate(limited,limited['identity'],'scripted_refinement')},'corruption_fixture':{'kind':'postexecution_observation_text_corruption','changed_trial_ids':corrupt_ids,'report':corrupt_report,'gate':release_gate(corrupt_report,corrupt_report['identity'],'scripted_refinement')},'actual_tool_failure':{'report':failed_report,'gate':release_gate(failed_report,failed_report['identity'],'scripted_refinement')},'missing_target_binding':missing_result,'identity_mismatch_gate':release_gate(normal,{**normal['identity'],'corpus_id':'different'},'scripted_refinement'),'scope':'Two deterministic repetitions of four original development cases only. Labels join after execution. Unsupported cases remain incomplete, excluded from supported denominator. Local threshold policy is not a model-quality release claim. Source verifier reconstructs successful deterministic tool receipts; failed-call causes are not authenticated. No generated answers, held-out queries or uncertainty estimate.'}
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();result=run();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'execution_mode':result['execution_mode'],'normal_gates':{k:v['status'] for k,v in result['release_gates'].items()},'step_budget_gate':result['step_budget']['gate']['status'],'corrupt_read_gate':result['corruption_fixture']['gate']['status'],'actual_tool_failure_gate':result['actual_tool_failure']['gate']['status'],'missing_target':result['missing_target_binding']['status'],'identity_mismatch':result['identity_mismatch_gate']['status']}))
