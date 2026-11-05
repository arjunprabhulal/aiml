"""Record real local HTTP requests. Gemini mode needs explicit execution approval."""
import argparse,json,os,socket,subprocess,sys,time,urllib.request,urllib.error,signal
from pathlib import Path
from assistant import Assistant,Ask,digest
from providers import Gemini
ROOT=Path(__file__).parent
LIVE_CASES=[
 {'id':'rollback','question':'How do I roll back a staging deployment?','version':'3.5'},
 {'id':'rotate-token','question':'How do I rotate an API token?','version':'3.5'},
 {'id':'previous-version','question':'How do I deploy staging with docuctl 3.4?','version':'3.4'},
 {'id':'production','question':'How does a maintainer deploy production?','version':'3.5','collection':'operations','maintainer':True}]

def plan():
    Gemini.transport()  # Validate the installed CA bundle without credentials or a request.
    service=Assistant();rows=[]
    for row in LIVE_CASES:
        role='maintainer' if row.get('maintainer') else 'reader'
        req=Ask(question=row['question'],version=row['version'],collection=row.get('collection','handbook'))
        passages,_=service.retrieve('capture',role,req)
        admitted=[];used=0
        for p in passages:
            n=len(json.dumps({'id':p.id,'text':p.text},ensure_ascii=False).encode())
            if used+n<=service.context_bytes:admitted.append(p);used+=n
        payload=Gemini.payload(req.question,admitted)
        rows.append({'case':row['id'],'payload':payload,'payload_sha256':digest(payload),'serialized_bytes':len(json.dumps(payload).encode())})
    return {'max_generation_HTTP_attempts':4,'max_output_tokens_per_attempt':1024,'thinking':'LOW','retries':0,'tools':[],
        'endpoint':'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent',
        'provider_timeout_seconds':35,'whole_process_seconds':180,'cases':rows}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--provider',choices=['extractive','gemini'],default='extractive')
    parser.add_argument('--execute-approved',action='store_true');parser.add_argument('--output',default='runs/http-demo.json');args=parser.parse_args()
    if args.provider=='gemini' and not args.execute_approved:
        print(json.dumps(plan(),indent=2));return
    if args.provider=='gemini':
        if not hasattr(signal,'SIGALRM'):raise RuntimeError('This recorder requires a process alarm')
        def deadline(*_):raise TimeoutError('Execution deadline reached')
        signal.signal(signal.SIGALRM,deadline);signal.alarm(170)
    output=Path(args.output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env['CAPSTONE_PROVIDER']=args.provider;env['CAPSTONE_RECORD_DIR']=str(output.parent/'provider-responses')
    env['DOCS_READER_TOKEN']='reader-demo-token';env['DOCS_MAINTAINER_TOKEN']='maintainer-demo-token'
    if args.provider=='extractive':
        for key in ['GOOGLE_API_KEY','GEMINI_API_KEY']:env.pop(key,None)
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(16);port=sock.getsockname()[1]
    log=output.with_suffix('.server.log');rows=[]
    started=time.monotonic()
    with log.open('w') as handle:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','api:app','--fd',str(sock.fileno()),'--log-level','error'],cwd=ROOT,
            env=env,pass_fds=(sock.fileno(),),stdout=handle,stderr=subprocess.STDOUT)
        sock.close()
        base=f'http://127.0.0.1:{port}'
        try:
            for _ in range(80):
                if process.poll() is not None:raise RuntimeError('Server stopped during startup')
                try:
                    with urllib.request.urlopen(base+'/health',timeout=.5) as r:health=json.load(r)
                    break
                except (OSError,ValueError):time.sleep(.1)
            else:raise RuntimeError('Server startup timed out')
            activities=list(LIVE_CASES)
            if args.provider=='extractive':activities += [dict(LIVE_CASES[0],id='repeat-rollback'),
                {'id':'unknown','question':'Who won Wimbledon?','version':'3.5'},
                {'id':'reader-denied','question':'How do I deploy production?','version':'3.5','collection':'operations'}]
            for row in activities:
                if time.monotonic()-started>165:raise RuntimeError('Batch deadline reached')
                body={k:v for k,v in row.items() if k in ['question','version','collection']}
                token='maintainer-demo-token' if row.get('maintainer') else 'reader-demo-token'
                request=urllib.request.Request(base+'/api/ask',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
                try:
                    with urllib.request.urlopen(request,timeout=40) as r:status=r.status;result=json.load(r)
                except urllib.error.HTTPError as e:status=e.code;result=json.loads(e.read())
                rows.append({'id':row['id'],'request':body,'status':status,'response':result})
                output.write_text(json.dumps({'provider':args.provider,'snapshot':health['snapshot'],'activities':rows},indent=2)+'\n')
                print(f"{row['id']}: HTTP {status} · {result.get('status',result.get('error',''))}",flush=True)
                if 'answer'in result:print(result['answer'],flush=True)
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    if args.provider=='gemini':signal.alarm(0)
    print(f'Provider: {args.provider}. Saved {len(rows)} real HTTP activities.',flush=True)
if __name__=='__main__':main()
