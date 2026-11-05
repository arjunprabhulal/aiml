"""Compare two frozen scripted policies using post-execution source checks."""
import copy
import hashlib
from tools import DocumentationTools
from refine import ScriptedPolicy
from limits import Limits,run_limited
from version_documents import validate_snapshot

SHARED_LIMITS=Limits(max_steps=6,max_searches=2,max_reads=2,max_source_bytes=4096)


class FixedPipeline:
    """Exactly one broad search and its first read, without a feedback branch."""
    def __init__(self,question,version):
        self.question=question;self.version=version;self.terminal_status=None;self.reason=None

    def __call__(self,observations):
        if not observations:return {'tool':'search','arguments':{'query':'text','version':self.version,'k':2}}
        if observations[-1]['tool']=='search':
            handles=observations[-1]['result']['results']
            if handles:return {'tool':'read','arguments':{'handle':copy.deepcopy(handles[0])}}
            self.terminal_status='incomplete';self.reason='no_search_results';return None
        self.terminal_status='completed';self.reason='fixed_pipeline_done';return None


def bind_targets(snapshot,cases):
    validate_snapshot(snapshot)
    labels={};receipts=[]
    for case in cases:
        if case['split']!='development':raise ValueError('development_only')
        if case['id'] in labels:raise ValueError('duplicate_case')
        targets=[];target_bindings=[]
        for target in case['expected']['targets']:
            matches=[(source,chunk) for source in snapshot['documents'] if source['source_id']==target['source_id'] and source['version']==target['source_version'] and source['sha256']==target['source_text_sha256'] for chunk in source['chunks'] if hashlib.sha256(chunk['text'].encode('utf-8')).hexdigest()==target['chunk_text_sha256']]
            if len(matches)!=1:raise ValueError('target_binding_not_bijective')
            source,chunk=matches[0]
            pid=chunk['chunk_id']
            target_bindings.append({'passage_id':pid,'source_id':source['source_id'],'version':source['version'],'source_sha256':source['sha256'],'text_sha256':chunk['text_sha256'],'document_revision':source['document_revision'],'start_line':chunk['start_line'],'end_line':chunk['end_line']})
            if pid in targets:raise ValueError('duplicate_target')
            targets.append(pid);receipts.append({'case_id':case['id'],'legacy_chunk_id':target['chunk_id'],'current_passage_id':pid,'binding':['source_id','source_version','source_text_sha256','chunk_text_sha256']})
        if case['class']=='answerable' and not targets:raise ValueError('answerable_requires_targets')
        if case['class']!='answerable' and targets:raise ValueError('unsupported_has_targets')
        labels[case['id']]={'case_class':case['class'],'target_passage_ids':targets,'target_bindings':target_bindings}
    return labels,receipts


def execute(snapshot,questions,limits=SHARED_LIMITS):
    """Only ID/question/version projections enter either policy; no labels."""
    trials=[]
    for question in questions:
        for name,policy_class in [('fixed_pipeline',FixedPipeline),('scripted_refinement',ScriptedPolicy)]:
            tools=DocumentationTools(snapshot);policy=policy_class(question['question'],question['version'])
            try:runtime=run_limited(tools,policy,limits)
            finally:tools.close()
            trials.append({'case_id':question['case_id'],'question':question['question'],'version':question['version'],'policy':name,'policy_terminal_status':policy.terminal_status,'policy_reason':policy.reason,'runtime':runtime})
    return trials


def check_outcome(trial,label):
    runtime=trial['runtime'];targets=label['target_passage_ids']
    read_rows=[observation['result'] for observation in runtime['observations'] if observation['tool']=='read']
    reads=[row['passage_id'] for row in read_rows]
    matched=[target['passage_id'] for target in label['target_bindings'] if any(all(row.get(key)==value for key,value in target.items()) and hashlib.sha256(row.get('text','').encode('utf-8')).hexdigest()==target['text_sha256'] for row in read_rows)]
    if not targets:return {'status':'incomplete','reason':'unsupported_fixture_has_no_retrieval_target','read_passage_ids':reads,'target_passage_ids':[]}
    if runtime['controller_status']=='failed':status,reason='fail','controller_or_tool_failure'
    elif runtime['controller_status']=='limited':status,reason='incomplete','admission_limit'
    elif set(targets)<=set(matched):status,reason='pass','all_bound_target_passages_read'
    elif trial['policy_terminal_status']=='incomplete':status,reason='incomplete','policy_stopped_without_target'
    else:status,reason='fail','target_passage_not_read'
    return {'status':status,'reason':reason,'read_passage_ids':reads,'target_passage_ids':list(targets)}


def evaluate(trials,labels):
    expected={(case_id,name) for case_id in labels for name in ('fixed_pipeline','scripted_refinement')}
    actual=[(t['case_id'],t['policy']) for t in trials]
    if len(actual)!=len(set(actual)) or set(actual)!=expected:raise ValueError('trial_join_mismatch')
    checked=[{**trial,'outcome_check':check_outcome(trial,labels[trial['case_id']])} for trial in trials]
    summary={}
    for policy in ('fixed_pipeline','scripted_refinement'):
        selected=[t for t in checked if t['policy']==policy]
        summary[policy]={status:sum(t['outcome_check']['status']==status for t in selected) for status in ('pass','fail','incomplete')}
    return checked,summary
