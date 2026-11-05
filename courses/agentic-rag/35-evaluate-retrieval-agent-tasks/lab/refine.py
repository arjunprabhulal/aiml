"""A deterministic retrieval controller with explicit question-only rewrite rules."""
import copy
import re
from tools import DocumentationTools,load_snapshot,ToolError

RULES=(
 ('existing-path',('existing','overwrite','replace'),'overwritten','overwritten'),
 ('json-result',('json',),'json','JSON string'),
 ('read-text',('reading','read'),'read','opens a file'),
 ('write-text',('saving','write','pathlib'),'write','write_text'),
)

def rule_for(question):
    if not isinstance(question,str) or not question.strip() or len(question)>512:raise ValueError('invalid_question')
    words=set(re.findall('[a-z0-9]+',question.lower()))
    for name,cues,query,marker in RULES:
        if words.intersection(cues):return {'name':name,'initial_query':'text','refinement_query':query,'required_marker':marker,'max_rounds':2}
    return {'name':'no-matching-rule','initial_query':'text','refinement_query':None,'required_marker':None,'max_rounds':2}

class ScriptedPolicy:
    def __init__(self,question,version,config=None):
        default=rule_for(question)
        self.question=question;self.config=default if config is None else copy.deepcopy(config)
        if not isinstance(version,str) or re.fullmatch(r'[0-9]+\.[0-9]+',version) is None:raise ValueError('invalid_version')
        self.version=version;self.terminal_status=None;self.reason=None
        config=self.config
        if not isinstance(config,dict) or set(config)!={'name','initial_query','refinement_query','required_marker','max_rounds'}:raise ValueError('invalid_policy')
        if not isinstance(config['name'],str) or not config['name']:raise ValueError('invalid_policy')
        for key in ('initial_query','refinement_query'):
            value=config[key]
            if key=='refinement_query' and value is None:continue
            if not isinstance(value,str) or re.fullmatch('[a-z0-9]{1,64}',value) is None:raise ValueError('invalid_policy')
        if config['required_marker'] is not None and (not isinstance(config['required_marker'],str) or not config['required_marker'] or len(config['required_marker'])>128):raise ValueError('invalid_policy')
        if type(config['max_rounds']) is not int or not 1<=config['max_rounds']<=3:raise ValueError('invalid_policy')
    def stop(self,status,reason):self.terminal_status=status;self.reason=reason;return None
    def __call__(self,observations):
        if not isinstance(observations,list) or any(not isinstance(o,dict) or set(o)!={'tool','arguments','result'} or o['tool'] not in ('search','read') for o in observations):raise ValueError('invalid_observations')
        searches=[o for o in observations if o['tool']=='search'];reads=[o for o in observations if o['tool']=='read']
        if not observations:return {'tool':'search','arguments':{'query':self.config['initial_query'],'version':self.version,'k':2}}
        last=observations[-1]
        if last['tool']=='search':
            already={o['result']['passage_id'] for o in reads}
            eligible=[row for row in last['result']['results'] if row['passage_id'] not in already]
            if eligible:return {'tool':'read','arguments':{'handle':copy.deepcopy(eligible[0])}}
            reason='no_match' if not last['result']['results'] else 'no_new_passages'
            if reason=='no_new_passages':return self.stop('incomplete',reason)
        else:
            marker=self.config['required_marker']
            if marker is not None and marker in last['result']['text']:return self.stop('completed','configured_context_marker_found')
            reason='marker_missing'
        if len(searches)>=self.config['max_rounds']:return self.stop('incomplete','round_limit')
        query=self.config['refinement_query']
        if query is None:return self.stop('incomplete','no_refinement_rule')
        previous=[o['arguments']['query'] for o in searches]
        if query in previous:return self.stop('incomplete','duplicate_query')
        return {'tool':'search','arguments':{'query':query,'version':self.version,'k':2}}

def run_controller(tools,question,version='3.12',config=None):
    policy=ScriptedPolicy(question,version,config);observations=[]
    try:
        # Local policy's maximum is 3 search/read rounds; guard against bugs too.
        for _ in range(7):
            action=policy(observations)
            if action is None:break
            result=getattr(tools,action['tool'])(**action['arguments'])
            if action['tool']=='read':tools.validate_read(result,action['arguments']['handle'])
            observations.append({'tool':action['tool'],'arguments':copy.deepcopy(action['arguments']),'result':result})
        else:return {'status':'failed','reason':'controller_step_guard','question':question,'version':version,'policy':policy.config,'observations':observations,'query_history':[o['arguments']['query'] for o in observations if o['tool']=='search']}
    except (ToolError,ValueError) as error:
        return {'status':'failed','reason':str(error),'question':question,'version':version,'policy':policy.config,'observations':observations,'query_history':[o['arguments']['query'] for o in observations if o['tool']=='search']}
    return {'status':policy.terminal_status,'reason':policy.reason,'question':question,'version':version,'policy':policy.config,'observations':observations,'query_history':[o['arguments']['query'] for o in observations if o['tool']=='search']}
