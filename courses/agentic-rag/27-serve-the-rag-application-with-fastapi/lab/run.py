"""Execute actual local HTTP requests against a Uvicorn subprocess."""
import argparse
import json
import hashlib
from pathlib import Path
from loopback import running_server
from service import validate_response,RetrieveRequest

QUESTION='Will write_text replace the contents of an existing file?'

def observe(client,name,payload=None,**options):
    response=client.post('/retrieve',json=payload,**options) if payload is not None else client.post('/retrieve',**options)
    return {'scenario':name,'http_status':response.status_code,'response':response.json(),'body_sha256_header':response.headers.get('X-Retrieval-Body-SHA256'),'raw_body_sha256':hashlib.sha256(response.content).hexdigest(),'raw_response_text':response.text}

def run():
    with running_server() as (client,lifecycle):
        health=client.get('/health').json();cases=[]
        for name,payload in [('completed',{'question':QUESTION}),('incomplete',{'question':'How frequently does our cloud provider back up these files?'}),('empty_eligible',{'question':QUESTION,'version':'9.99'}),('limited',{'question':QUESTION,'max_steps':1})]:
            observation=observe(client,name,payload);validate_response(observation['response'],RetrieveRequest.model_validate(payload),health['corpus_id']);cases.append(observation)
        cases.append(observe(client,'invalid_boolean_limit',{'question':QUESTION,'max_steps':True}))
        cases.append(observe(client,'extra_field',{'question':QUESTION,'fault':True}))
        cases.append(observe(client,'invalid_json',content=b'{broken',headers={'content-type':'application/json'}))
        cases.append(observe(client,'body_too_large_chunked',content=(piece for piece in [b'{"question":"',b'x'*4097,b'"}']),headers={'content-type':'application/json'}))
        cases.append(observe(client,'unsupported_media',content='question',headers={'content-type':'text/plain'}))
    with running_server('fault_fixture:app') as (client,fault_lifecycle):
        fault=observe(client,'trusted_controlled_tool_failure',{'question':QUESTION})
    return {'execution_mode':'actual-loopback-fastapi-http-offline-scripted-retrieval','model_called':False,'health':health,'cases':cases,'trusted_fault':fault,'lifecycle':lifecycle,'fault_lifecycle':fault_lifecycle,'interpretation':'Real local HTTP boundary plus scripted retrieval; no generated answers, external deployment, authorization, capacity or quality claim.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();result=run();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'execution_mode':result['execution_mode'],'cases':[{'scenario':case['scenario'],'http_status':case['http_status'],'status':case['response'].get('status',case['response'].get('error',{}).get('code'))} for case in result['cases']],'trusted_fault_http_status':result['trusted_fault']['http_status'],'clean_shutdown':result['lifecycle']['shutdown_complete_observed'] and result['fault_lifecycle']['shutdown_complete_observed']},sort_keys=True))
