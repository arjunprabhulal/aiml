"""Exercise a real local process gate, not a throughput benchmark."""
import argparse,json,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import httpx
from loopback import running_server
QUESTION='Will write_text replace the contents of an existing file?'
def state(client):return client.get('/health').json()['gate']
def until(client,predicate):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        current=state(client)
        if predicate(current):return current
        time.sleep(.005)
    raise RuntimeError('state_not_observed')
def post(client):
    r=client.post('/retrieve',json={'question':QUESTION});b=r.json()
    return {'http_status':r.status_code,'status':b.get('status',b.get('error',{}).get('code'))}
def run():
    with running_server('delay_fixture:app') as (client,lifecycle):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(post,client);active=until(client,lambda s:s['active']==1)
            second=pool.submit(post,client);queued=until(client,lambda s:s['waiting']==1)
            overflow=post(client);waiting=second.result();completed=first.result()
        idle=until(client,lambda s:s['active']==0 and s['waiting']==0)
        try:client.post('/retrieve',json={'question':QUESTION},timeout=.03);raise AssertionError('expected_timeout')
        except httpx.ReadTimeout:pass
        after_timeout=state(client);after_completion=until(client,lambda s:s['active']==0)
    with running_server('success_fixture:app') as (client,success_lifecycle):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(post,client);until(client,lambda s:s['active']==1)
            second=pool.submit(post,client);until(client,lambda s:s['waiting']==1)
            promoted_results=[first.result(),second.result()]
        promoted_state=state(client)
    with running_server('fault_fixture:app') as (client,fault_lifecycle):failure=post(client);failure_state=state(client)
    return {'execution_mode':'actual-concurrent-loopback-http-single-process','model_called':False,'controlled_delay_seconds':.35,'cases':{'active_observed':active,'queued_observed':queued,'queue_overflow':overflow,'wait_deadline':waiting,'first_completed':completed,'idle':idle,'client_timeout':{'client_exception':'ReadTimeout','server_after_timeout':after_timeout,'server_after_completion':after_completion},'fifo_promotion':{'responses':promoted_results,'state':promoted_state},'server_constructor_failure':{'response':failure,'state':failure_state}},'lifecycle':lifecycle,'success_lifecycle':success_lifecycle,'fault_lifecycle':fault_lifecycle,'scope':'Trusted fixture delay exposes admission states; not a latency or capacity benchmark. Client timeout did not cancel server work. Direct task cancellation is tested separately. Corpus setup is outside gate; SQLite tools are created per worker after admission.'}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();result=run();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'execution_mode':result['execution_mode'],'queue_overflow':result['cases']['queue_overflow'],'wait_deadline':result['cases']['wait_deadline'],'fifo_promotion':result['cases']['fifo_promotion']['responses'],'server_failure':result['cases']['server_constructor_failure']['response'],'idle_active':result['cases']['idle']['active']}))
