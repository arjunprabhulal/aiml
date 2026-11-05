"""Execute real local authorization requests and record their actual JSON replies."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from local_http import server

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();out=args.output.resolve();out.parent.mkdir(parents=True,exist_ok=True)
    observations=[]
    def request(client,name,path,payload,token='demo-editor'):
        response=client.post(path,json=payload,headers={'Authorization':'Bearer '+token} if token else {})
        row={'name':name,'method':'POST','path':path,'status_code':response.status_code,'body':response.json()};observations.append(row);return response
    with server(ROOT,out.parent/'normal-server') as client:
        query={'query':'file','collection':'files','k':2}
        request(client,'unknown_identity','/search',query,'unknown')
        request(client,'collection_denied','/search',query,'demo-reader')
        found=request(client,'authorized_search','/search',query)
        handle=found.json()['results'][0]
        request(client,'authorized_read','/read',{'handle':handle})
        request(client,'foreign_handle','/read',{'handle':handle},'demo-reader')
        tampered=dict(handle);tampered['start_line']+=1
        request(client,'tampered_handle','/read',{'handle':tampered})
        request(client,'eligible_before_k','/search',{'query':'file','collection':'serialization','k':1},'demo-reader')
        request(client,'invalid_boolean_k','/search',{**query,'k':True})
        request(client,'empty_matches','/search',{**query,'query':'zzzz'})
    with server(ROOT,out.parent/'failure-server','fixture_server:app') as client:request(client,'controlled_tool_failure','/search',query)
    expected=[401,403,200,200,403,403,200,422,200,503]
    assert [r['status_code'] for r in observations]==expected
    result={'schema_version':1,'mode':'actual-loopback-http-public-fixture-authorization','model_called':False,'observations':observations}
    out.write_text(json.dumps(result,indent=2)+'\n')
    record(out,['run.py','--output',str(args.output)],observations)

def record(out,command,observations):
    tests=subprocess.run([sys.executable,'-m','unittest','discover','-v'],cwd=ROOT,text=True,capture_output=True)
    (out.parent/'tests.txt').write_text(tests.stdout+tests.stderr)
    lines=[f"{r['name']}: HTTP {r['status_code']}"+(f" cache={r['body']['cache']}" if 'cache' in r['body'] else '') for r in observations];stdout='\n'.join(lines)+'\n';print(stdout,end='');(out.parent/'stdout.txt').write_text(stdout);(out.parent/'stderr.txt').write_text('')
    files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*')) if p.is_file() and 'runs' not in p.relative_to(ROOT).parts and '__pycache__' not in p.parts}
    execution={'command':[sys.executable,*sys.argv],'working_directory':str(Path.cwd()),'test_command':[sys.executable,'-m','unittest','discover','-v'],'test_exit_code':tests.returncode,'python':platform.python_version(),'packages':{n:importlib.metadata.version(n) for n in ['fastapi','starlette','uvicorn','httpx','pydantic']},'source_sha256':files,'result_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'network':'loopback only; no provider/model/download'}
    (out.parent/'execution.json').write_text(json.dumps(execution,indent=2)+'\n')
    if tests.returncode:raise SystemExit(tests.returncode)
if __name__=='__main__':main()
