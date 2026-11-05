"""Execute actual loopback requests and capture redacted local spans."""
import argparse,json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from loopback import running_server
QUESTION='Will write_text replace the contents of an existing file?'
def run():
    with running_server('app:app') as (client,lifecycle):
        def call(_):
            r=client.post('/retrieve',json={'question':QUESTION});b=r.json()
            return {'http_status':r.status_code,'execution_trace_id':r.headers['X-Execution-Trace-ID'],'content_request_id':b['request_id'],'status':b['status']}
        with ThreadPoolExecutor(max_workers=2) as pool:cases=list(pool.map(call,range(2)))
        limited=client.post('/retrieve',json={'question':QUESTION,'max_steps':0})
        cases.append({'http_status':limited.status_code,'execution_trace_id':limited.headers['X-Execution-Trace-ID'],'status':limited.json()['status']})
        invalid=client.post('/retrieve',json={'question':QUESTION,'max_steps':True})
        traces=client.get('/traces').json()
    with running_server('fault_fixture:app') as (client,fault_lifecycle):
        r=client.post('/retrieve',json={'question':QUESTION});failure={'http_status':r.status_code,'status':r.json()['status'],'execution_trace_id':r.headers['X-Execution-Trace-ID'],'record':client.get('/traces').json()}
    return {'execution_mode':'actual-loopback-local-structured-tracing','model_called':False,'cases':cases,'invalid_request_http_status':invalid.status_code,'record':traces,'controlled_tool_failure':failure,'lifecycle':lifecycle,'fault_lifecycle':fault_lifecycle,'scope':'Local bounded recorder; schema/body rejections occur before trace creation. Tool admission spans record actual core-admitted invocation, not denied actions. No raw questions or source text in spans; response content is not the trace log.'}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();result=run();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'execution_mode':result['execution_mode'],'cases':result['cases'],'failure_http_status':result['controlled_tool_failure']['http_status'],'retained_traces':result['record']['retention']['retained_traces']}))
