"""Trace a fixed docuctl document lookup across two local processes. No model request.

The worker accepts a W3C traceparent value in a JSON envelope on stdin. The fixture
uses derived IDs and a counting clock: durations are synthetic, not measured latency.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tracing import Tracer, DerivedIds, CountingClock, collect

HERE = Path(__file__).resolve().parent
PAGES = json.loads((HERE/'docuctl_pages.json').read_text())


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class EvidenceError(ValueError):
    pass


def evidence_verdict(citation, kept, current):
    if citation not in current:
        return 'unknown citation'
    if citation not in kept:
        return 'citation not sent to answer step'
    if kept[citation]['sha256'] != digest(current[citation]['text']):
        return 'stale evidence'
    return 'current kept source'


def worker(packet):
    spans=[]
    tracer=Tracer('docs-worker',spans.append,clock=CountingClock(),ids=DerivedIds('docuctl-worker'))
    with tracer.span('lookup',traceparent=packet.get('traceparent'),page_id=packet['page_id']):
        page=PAGES[packet['page_id']]
        text='Use an older staging command.' if packet.get('stale') else page['text']
        passage={'id':packet['page_id'],'version':page['version'],'text':text,'sha256':digest(text)}
    return {'passage':passage,'spans':spans}


def run(*, question='Which command deploys staging version 3.5?', propagate=True, stale=False, drop=False):
    spans=[];result={}
    tracer=Tracer('gateway',spans.append,clock=CountingClock(),ids=DerivedIds('docuctl-gateway'))
    try:
        with tracer.span('request',case_id='staging-deploy'):
            if not isinstance(question,str) or not question.strip():raise ValueError('question must contain text')
            with tracer.span('lookup.call',page_id='deploy-35') as current:
                packet={'page_id':'deploy-35','stale':stale}
                if propagate:packet['traceparent']=current.traceparent()
                process=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker'],
                    input=json.dumps(packet),text=True,capture_output=True,check=True,timeout=10)
                response=json.loads(process.stdout)
                spans.extend(response['spans'])
            with tracer.span('assemble',source_id=response['passage']['id'],source_sha256=response['passage']['sha256']):
                kept={} if drop else {response['passage']['id']:response['passage']}
            with tracer.span('provenance',citation_id='deploy-35') as check:
                verdict=evidence_verdict('deploy-35',kept,PAGES)
                check.set(verdict=verdict)
                if verdict!='current kept source':raise EvidenceError(verdict)
                result={'citation':'deploy-35','text':kept['deploy-35']['text'],'provenance':verdict}
    except (ValueError,EvidenceError) as error:
        result={'error':str(error)}
    return {'execution_mode':'fixed local lookup; two processes; no model request',
            'timing_clock':'synthetic counting clock; not measured latency',
            'result':result,'spans':spans,'traces':collect(spans)}

if __name__=='__main__':
    data=worker(json.load(sys.stdin)) if '--worker' in sys.argv else run()
    print(json.dumps(data,indent=2))
