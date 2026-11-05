"""Request-bound retrieval projection; scripted policy, no answer generation."""
import copy
from dataclasses import asdict
from typing import Annotated
from pydantic import BaseModel,ConfigDict,Field,field_validator
from tools import DocumentationTools
from refine import ScriptedPolicy
from limits import Limits,run_limited
from version_documents import canonical_hash

class RetrieveRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    question:Annotated[str,Field(min_length=1,max_length=512)]
    version:Annotated[str,Field(pattern=r'^[0-9]+\.[0-9]+$',max_length=16)]='3.12'
    max_steps:Annotated[int,Field(ge=0,le=12)]=6
    max_searches:Annotated[int,Field(ge=0,le=3)]=2
    max_reads:Annotated[int,Field(ge=0,le=3)]=2
    max_source_bytes:Annotated[int,Field(ge=0,le=4096)]=4096
    @field_validator('question')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():raise ValueError('blank_question')
        value.encode('utf-8')
        return value

def safe_trace(trace):
    result=copy.deepcopy(trace)
    for event in result:
        if event.get('status')=='failed':event['reason']='tool_failure'
        elif event.get('decision')=='refused':event['reason']='invalid_tool_action'
    return result

def retrieve(payload,snapshot,tool_factory=DocumentationTools):
    request=payload.model_dump();corpus_id=snapshot['snapshot_id']
    request_id=canonical_hash({'request':request,'corpus_id':corpus_id})
    limits=Limits(**{key:request[key] for key in ('max_steps','max_searches','max_reads','max_source_bytes')})
    policy=ScriptedPolicy(payload.question,payload.version)
    tools=tool_factory(snapshot)
    try:
        run=run_limited(tools,policy,limits)
        evidence=[]
        for event in run['trace']:
            if event.get('status')=='succeeded' and event['action']['tool']=='read':
                evidence.append(tools.validate_read(event['result'],event['action']['arguments']['handle']))
        status=run['controller_status']
        if status=='completed':status=policy.terminal_status or 'completed'
        reason='retrieval_failed' if status=='failed' else run['terminal_reason'] if status=='limited' else policy.reason or run['terminal_reason']
        body={'schema_version':1,'execution_mode':'offline-scripted-retrieval-http','model_called':False,
              'request_id':request_id,'corpus_id':corpus_id,'request':request,'status':status,'reason':reason,
              'admission':{'accepted':True,'limits':asdict(limits)},'usage':run['usage'],'trace':safe_trace(run['trace']),
              'evidence':evidence,'policy':policy.config}
        body['result_sha256']=canonical_hash(body)
        return (503 if status=='failed' else 200),body
    finally:tools.close()

def validate_response(body,payload,corpus_id):
    """Consistency check for a saved response; not network authentication."""
    if isinstance(payload,RetrieveRequest):payload=payload.model_dump()
    expected=RetrieveRequest.model_validate(payload).model_dump()
    if not isinstance(body,dict) or canonical_hash(body.get('request'))!=canonical_hash(expected) or body.get('corpus_id')!=corpus_id:raise ValueError('response_request_mismatch')
    if body.get('request_id')!=canonical_hash({'request':expected,'corpus_id':corpus_id}):raise ValueError('response_request_mismatch')
    if body.get('result_sha256')!=canonical_hash({key:value for key,value in body.items() if key!='result_sha256'}):raise ValueError('response_hash_mismatch')
    return body
