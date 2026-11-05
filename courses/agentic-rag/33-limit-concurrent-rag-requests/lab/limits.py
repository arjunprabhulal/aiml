"""Admission limits for an offline scripted tool controller, not a model agent."""
import copy
from dataclasses import asdict,dataclass
import json
import re


@dataclass(frozen=True)
class Limits:
    max_steps:int=6
    max_searches:int=2
    max_reads:int=2
    max_source_bytes:int=4096

    def __post_init__(self):
        for key,value in asdict(self).items():
            maximum=16_777_216 if key=='max_source_bytes' else 100
            if type(value) is not int or not 0<=value<=maximum:raise ValueError('invalid_'+key)


def action_cost(tools,action):
    if not isinstance(action,dict) or set(action)!={'tool','arguments'}:raise ValueError('invalid_action_schema')
    tool=action['tool'];arguments=action['arguments']
    if not isinstance(tool,str) or tool not in ('search','read'):raise ValueError('unknown_tool')
    if not isinstance(arguments,dict):raise ValueError('invalid_arguments')
    if tool=='search':
        if not {'query','version'}<=set(arguments) or set(arguments)-{'query','version','k'}:raise ValueError('invalid_search_arguments')
        if not isinstance(arguments['query'],str) or re.fullmatch(r'[A-Za-z0-9]{1,64}',arguments['query']) is None:raise ValueError('invalid_search_query')
        if not isinstance(arguments['version'],str) or re.fullmatch(r'[0-9]+\.[0-9]+',arguments['version']) is None:raise ValueError('invalid_search_version')
        if type(arguments.get('k',2)) is not int or not 1<=arguments.get('k',2)<=10:raise ValueError('invalid_search_k')
        return 0
    if set(arguments)!={'handle'} or not isinstance(arguments['handle'],dict):raise ValueError('invalid_read_arguments')
    cost=tools.read_cost(arguments['handle'])
    if type(cost) is not int or cost<0:raise ValueError('invalid_read_cost')
    return cost


def run_limited(tools,policy,limits=Limits()):
    """Validate, reserve, then invoke. Corpus setup is outside these counters."""
    if not isinstance(limits,Limits):raise ValueError('invalid_limits')
    usage={'steps':0,'searches':0,'reads':0,'reserved_source_bytes':0,'delivered_source_bytes':0}
    observations=[];trace=[];seen=set()
    status='completed';reason='policy_complete'
    while True:
        try:
            action=policy(copy.deepcopy(observations))
            if action is None:break
            cost=action_cost(tools,action)
            canonical=copy.deepcopy(action)
            if action['tool']=='search':canonical['arguments']={'query':action['arguments']['query'].lower(),'version':action['arguments']['version'],'k':action['arguments'].get('k',2)}
            fingerprint=json.dumps(canonical,sort_keys=True,separators=(',',':'),allow_nan=False)
            if fingerprint in seen:raise ValueError('repeated_action')
        except Exception as error:
            status='failed';reason=type(error).__name__+': '+str(error)
            trace.append({'decision':'refused','reason':reason,'invoked':False});break
        tool=action['tool']
        checks=[('max_steps',usage['steps']+1,limits.max_steps),('max_searches',usage['searches']+(tool=='search'),limits.max_searches),('max_reads',usage['reads']+(tool=='read'),limits.max_reads),('max_source_bytes',usage['reserved_source_bytes']+cost,limits.max_source_bytes)]
        denied=next((name for name,requested,maximum in checks if requested>maximum),None)
        if denied:
            status='limited';reason=denied
            trace.append({'action':copy.deepcopy(action),'decision':'denied','reason':denied,'invoked':False,'preflight_source_bytes':cost});break
        seen.add(fingerprint)
        usage['steps']+=1;usage['searches']+=int(tool=='search');usage['reads']+=int(tool=='read');usage['reserved_source_bytes']+=cost
        event={'action':copy.deepcopy(action),'decision':'executed','invoked':True,'reserved_source_bytes':cost}
        try:
            result=tools.search(**action['arguments']) if tool=='search' else tools.read(action['arguments']['handle'])
            if tool=='read':
                result=tools.validate_read(result,action['arguments']['handle'])
                if not isinstance(result,dict) or not isinstance(result.get('text'),str):raise ValueError('invalid_read_result')
                received=len(result['text'].encode('utf-8'));usage['delivered_source_bytes']+=received
                if received!=cost:raise ValueError('read_size_contract_changed')
            event['status']='succeeded';event['result']=copy.deepcopy(result)
            observations.append({'tool':tool,'arguments':copy.deepcopy(action['arguments']),'result':copy.deepcopy(result)})
        except Exception as error:
            status='failed';reason=type(error).__name__+': '+str(error)
            event['status']='failed';event['reason']=reason
        event['usage_after']=dict(usage);trace.append(event)
        if status=='failed':break
    return {'controller_status':status,'terminal_reason':reason,'limits':asdict(limits),'usage':usage,'trace':trace,'observations':observations,'scope':'Offline scripted tool policy. Corpus initialization is outside action counters. Source bytes are reserved read-text UTF-8 bytes, not disk I/O or model tokens.'}
