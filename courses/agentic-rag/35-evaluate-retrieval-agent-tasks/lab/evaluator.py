"""Fixture task outcomes, independent operational checks, and explicit release policy."""
import copy
from dataclasses import asdict
from compare import execute,bind_targets,check_outcome
from limits import Limits,action_cost
from tools import DocumentationTools
from version_documents import canonical_hash,validate_snapshot

DEFAULT_CONFIG={'limits':{'max_steps':6,'max_searches':2,'max_reads':2,'max_source_bytes':4096},'policies':['fixed_pipeline','scripted_refinement'],'repeats':2}
GATE_POLICY={'minimum_supported_pass_fraction':1.0,'maximum_integrity_failures':0,'require_deterministic_repeats':True}

def validate_config(config):
    if not isinstance(config,dict) or set(config)!={'limits','policies','repeats'}:raise ValueError('invalid_configuration')
    if config['policies']!=['fixed_pipeline','scripted_refinement']:raise ValueError('invalid_policies')
    if type(config['repeats']) is not int or not 2<=config['repeats']<=10:raise ValueError('invalid_repeats')
    if not isinstance(config['limits'],dict) or set(config['limits'])!=set(asdict(Limits())):raise ValueError('invalid_limits')
    Limits(**config['limits']);return copy.deepcopy(config)

def execute_trials(snapshot,questions,config):
    """Only case ID, question and version cross the execution boundary."""
    validate_snapshot(snapshot);config=validate_config(config)
    if not isinstance(questions,list) or not questions:raise ValueError('invalid_questions')
    for q in questions:
        if not isinstance(q,dict) or set(q)!={'case_id','question','version'}:raise ValueError('execution_projection_only')
        if not all(isinstance(v,str) and v for v in q.values()):raise ValueError('invalid_question')
    if len({q['case_id'] for q in questions})!=len(questions):raise ValueError('duplicate_question')
    trials=[]
    for repeat in range(1,config['repeats']+1):
        for trial in execute(snapshot,copy.deepcopy(questions),Limits(**config['limits'])):
            trial['repeat']=repeat;trial['trial_id']=canonical_hash({'case_id':trial['case_id'],'policy':trial['policy'],'repeat':repeat,'configuration':config,'corpus_id':snapshot['snapshot_id']});trials.append(trial)
    return trials

def check_integrity(snapshot,trial,limits):
    """Rebuild issued handles in a fresh verifier; never use target labels here."""
    tools=DocumentationTools(snapshot)
    try:
        runtime=trial['runtime']
        if canonical_hash(runtime['limits'])!=canonical_hash(limits):raise ValueError('limits_mismatch')
        usage={'steps':0,'searches':0,'reads':0,'reserved_source_bytes':0,'delivered_source_bytes':0};observations=[];seen=set();terminal=False
        for event in runtime['trace']:
            if terminal:raise ValueError('event_after_terminal')
            if event['decision']=='refused':
                if event.get('invoked') is not False:raise ValueError('refused_invoked')
                terminal=True;continue
            action=event['action'];tool=action['tool'];cost=action_cost(tools,action)
            if tool=='search' and action['arguments']['version']!=trial['version']:raise ValueError('ineligible_version')
            fingerprint=canonical_hash({'tool':tool,'arguments':({'query':action['arguments']['query'].lower(),'version':action['arguments']['version'],'k':action['arguments'].get('k',2)} if tool=='search' else action['arguments'])})
            next_usage={**usage,'steps':usage['steps']+1,'searches':usage['searches']+int(tool=='search'),'reads':usage['reads']+int(tool=='read'),'reserved_source_bytes':usage['reserved_source_bytes']+cost}
            checks=[('max_steps',next_usage['steps']),('max_searches',next_usage['searches']),('max_reads',next_usage['reads']),('max_source_bytes',next_usage['reserved_source_bytes'])]
            denied=next((name for name,value in checks if value>limits[name]),None)
            if event['decision']=='denied':
                if event.get('invoked') is not False or not denied or event['reason']!=denied or event['preflight_source_bytes']!=cost:raise ValueError('invalid_denial')
                terminal=True;continue
            if event['decision']!='executed' or event.get('invoked') is not True or denied or fingerprint in seen:raise ValueError('invalid_admission')
            if event['reserved_source_bytes']!=cost:raise ValueError('reservation_mismatch')
            seen.add(fingerprint);usage=next_usage
            if event['status']=='succeeded':
                if tool=='search':
                    expected=tools.search(**action['arguments'])
                    if canonical_hash(expected)!=canonical_hash(event['result']):raise ValueError('search_provenance')
                else:
                    tools.validate_read(event['result'],action['arguments']['handle']);usage['delivered_source_bytes']+=cost
                observations.append({'tool':tool,'arguments':action['arguments'],'result':event['result']})
            elif event['status']=='failed':
                if 'result' in event:raise ValueError('failed_has_result')
                terminal=True
            else:raise ValueError('invalid_event_status')
            if canonical_hash(usage)!=canonical_hash(event['usage_after']):raise ValueError('usage_progression')
        if canonical_hash(usage)!=canonical_hash(runtime['usage']):raise ValueError('usage_total')
        if canonical_hash(observations)!=canonical_hash(runtime['observations']):raise ValueError('observation_trace_mismatch')
        status=runtime['controller_status']
        if status not in ('completed','limited','failed'):raise ValueError('invalid_terminal')
        if status=='limited' and (not runtime['trace'] or runtime['trace'][-1]['decision']!='denied'):raise ValueError('limited_without_denial')
        if status=='failed' and (not runtime['trace'] or not (runtime['trace'][-1]['decision']=='refused' or runtime['trace'][-1].get('status')=='failed')):raise ValueError('failed_without_failure')
        if status=='completed' and terminal:raise ValueError('completed_after_terminal')
        return {'status':'pass','reason':'trace_budget_and_successful_source_bindings_match','verified_read_count':len([o for o in observations if o['tool']=='read'])}
    except (ValueError,KeyError,TypeError,OverflowError):return {'status':'fail','reason':'trace_budget_or_provenance_mismatch','verified_read_count':0}
    finally:tools.close()

def check_trial(snapshot,trial,label,limits):
    integrity=check_integrity(snapshot,trial,limits)
    outcome=check_outcome(trial,label)
    if integrity['status']=='fail':outcome={**outcome,'status':'fail','reason':'execution_integrity_failure'}
    return {**copy.deepcopy(trial),'execution_integrity':integrity,'controller_terminal':trial['runtime']['controller_status'],'task_outcome':outcome}

def evaluate_run(snapshot,cases,trials,config):
    config=validate_config(config)
    # Labels are bound only after all trial execution has returned.
    labels,receipts=bind_targets(snapshot,cases)
    questions=[{'case_id':c['id'],'question':c['input'],'version':c['tags']['python_version']} for c in cases]
    identity={'corpus_id':snapshot['snapshot_id'],'configuration_id':canonical_hash(config),'cases_id':canonical_hash(cases),'checker_policy_id':canonical_hash({'version':1,'gate_policy':GATE_POLICY})}
    expected={(q['case_id'],p,r) for q in questions for p in config['policies'] for r in range(1,config['repeats']+1)}
    actual=[(t['case_id'],t['policy'],t['repeat']) for t in trials]
    if len(actual)!=len(set(actual)) or set(actual)!=expected:raise ValueError('trial_join_mismatch')
    by_id={q['case_id']:q for q in questions}
    for t in trials:
        q=by_id[t['case_id']]
        if t['question']!=q['question'] or t['version']!=q['version']:raise ValueError('question_binding_mismatch')
        expected_id=canonical_hash({'case_id':t['case_id'],'policy':t['policy'],'repeat':t['repeat'],'configuration':config,'corpus_id':snapshot['snapshot_id']})
        if t['trial_id']!=expected_id:raise ValueError('trial_id_mismatch')
    checked=[check_trial(snapshot,t,labels[t['case_id']],config['limits']) for t in trials]
    return {'identity':identity,'configuration':config,'target_binding_receipts':receipts,'labels':labels,'trials':checked,'expected_trial_count':len(expected)}

def release_gate(report,expected_identity,policy_name):
    """These thresholds are explicit fixture policy, not general model quality."""
    if report['identity']!=expected_identity or report['identity'].get('checker_policy_id')!=canonical_hash({'version':1,'gate_policy':GATE_POLICY}) or report['identity']['configuration_id']!=canonical_hash(report['configuration']) or policy_name not in report['configuration']['policies']:
        return {'status':'NOTCOMPARABLE','reason':'identity_or_policy_mismatch','thresholds':GATE_POLICY}
    selected=[t for t in report['trials'] if t['policy']==policy_name]
    repeats=report['configuration']['repeats'];labels=report['labels']
    keys=[(t['case_id'],t['repeat']) for t in selected]
    if len(keys)!=len(set(keys)) or set(keys)!={(case,r) for case in labels for r in range(1,repeats+1)}:
        return {'status':'NOTCOMPARABLE','reason':'missing_or_duplicate_trials','thresholds':GATE_POLICY}
    deterministic=all(len({canonical_hash({key:t[key] for key in ('runtime','policy_terminal_status','policy_reason')}) for t in selected if t['case_id']==case})==1 for case in labels)
    if not deterministic:return {'status':'NOTCOMPARABLE','reason':'repeat_disagreement','thresholds':GATE_POLICY}
    supported=[t for t in selected if labels[t['case_id']]['target_passage_ids']]
    if not supported:return {'status':'NOTCOMPARABLE','reason':'no_supported_targets','thresholds':GATE_POLICY}
    counts={status:sum(t['task_outcome']['status']==status for t in supported) for status in ('pass','fail','incomplete')}
    integrity_failures=sum(t['execution_integrity']['status']=='fail' for t in selected)
    passed=counts['pass']==len(supported) and integrity_failures==0
    return {'status':'PASS' if passed else 'FAIL','reason':'fixture_thresholds_met' if passed else 'fixture_thresholds_not_met','thresholds':GATE_POLICY,'supported_trials':len(supported),'supported_outcomes':counts,'unsupported_trials':len(selected)-len(supported),'integrity_failures':integrity_failures,'deterministic_repeats':deterministic}
