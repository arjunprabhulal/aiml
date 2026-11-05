"""Execute derived local frame replay; no provider streaming or inference."""
import argparse
import json
from pathlib import Path
from stream_core import DEVELOPMENT_CASES,RECORDING_SHA256,load_binding,replay_frames,encode_frames,byte_fragments,consume

def run():
    cases=[]
    for case_id in DEVELOPMENT_CASES:
        binding,raw=load_binding(case_id);frames=replay_frames(case_id,request=binding)
        result=consume(byte_fragments(encode_frames(frames)),binding)
        cases.append({'case_id':case_id,'request_sha256':binding['request_sha256'],'selected_source_ids':[r['source_id'] for r in binding['selected_context']],'original_complete_content_preserved':result['provisional_content']==raw,'result':result})
    binding,_=load_binding('replace-file')
    failures=[]
    for terminal in ('cancel','error'):
        result=consume(byte_fragments(encode_frames(replay_frames('replace-file',terminal=terminal))),binding)
        failures.append({'scenario':'controlled_local_'+terminal,'result':result})
    frames=replay_frames('replace-file');partial=encode_frames(frames[:-1])
    failures.append({'scenario':'controlled_transport_eof_before_terminal','result':consume(byte_fragments(partial),binding)})
    def broken_transport():
        yield encode_frames(frames[:2])
        raise OSError('controlled local producer failure')
    failures.append({'scenario':'controlled_local_transport_io_error','result':consume(broken_transport(),binding)})
    return {'execution_mode':'offline-derived-ndjson-frame-replay','model_called':False,'original_recording_sha256':RECORDING_SHA256,'provenance':'Original complete model messages reframed locally; no provider delta boundaries, token timings or fresh inference recorded.','development_cases':cases,'controlled_failures':failures,'interpretation':'Schema and known-context citation validation are protocol checks, not factual answer or citation-support review.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();result=run()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'execution_mode':result['execution_mode'],'development_cases':[{'case_id':c['case_id'],'status':c['result']['status'],'answer_status':c['result']['accepted_answer']['status'] if c['result']['accepted_answer'] else None,'application_frames':c['result']['stats']['application_frames'],'transport_fragments':c['result']['stats']['transport_fragments']} for c in result['development_cases']],'controlled_failures':[{'scenario':f['scenario'],'status':f['result']['status'],'accepted_answer':f['result']['accepted_answer']} for f in result['controlled_failures']]},sort_keys=True))
