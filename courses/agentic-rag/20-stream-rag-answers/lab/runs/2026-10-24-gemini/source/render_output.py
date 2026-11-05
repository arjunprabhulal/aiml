"""Render actual local replay results without fabricating provider streaming."""
import argparse
from html import escape
import json
from pathlib import Path

def render(result):
    cards=[]
    for case in result['development_cases']:
        run=case['result'];answer=run['accepted_answer']
        cards.append('<article><h2>'+escape(case['case_id'])+'</h2><p>Local transport: <strong>'+escape(run['status'])+'</strong> · Answer status: '+escape(answer['status'] if answer else 'not accepted')+'</p><p>'+str(run['stats']['transport_fragments'])+' byte fragments → '+str(run['stats']['application_frames'])+' application frames</p><blockquote>'+escape(answer['answer'] if answer else 'No accepted answer')+'</blockquote><p>Validated source IDs: '+escape(', '.join(c['source_id'] for c in run['citations']) or 'none')+'</p></article>')
    failures=[]
    for failure in result['controlled_failures']:
        run=failure['result'];failures.append('<li><strong>'+escape(failure['scenario'])+'</strong><p>Status '+escape(run['status'])+' · Accepted answer: none · Citations: none</p><p>'+str(len(run['provisional_content']))+' provisional characters retained</p></li>')
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Local RAG frame consumer</title><style>*{box-sizing:border-box}body{margin:0;font:17px/1.5 system-ui,sans-serif;color:#192136;background:#fff}main{max-width:1100px;margin:auto;padding:32px 24px}h1{font-size:32px;margin:0 0 12px}h2{font-size:23px;margin:0 0 12px}p{margin:10px 0;overflow-wrap:anywhere}.mode{color:#596375}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}article{border:1.5px solid #192136;border-radius:8px;padding:18px;background:#dcfce7}blockquote{margin:16px 0;border-left:3px solid #274bc4;padding-left:12px;overflow-wrap:anywhere}ul{padding:0;list-style:none}li{border:1.5px dashed #b91c1c;background:#ffe4e6;padding:16px;margin:12px 0;overflow-wrap:anywhere}@media(max-width:700px){main{padding:24px 16px}.grid{grid-template-columns:1fr}h1{font-size:27px}}</style><main><h1>Local RAG frame consumer</h1><p class="mode">Actual offline application-frame replay · No new inference or provider-stream recording</p><p>Original complete Gemma JSON messages were framed locally. Byte-fragment and application-frame counts describe this local transport, not provider deltas, tokens or timing. Acceptance requires terminal done, EOF, full JSON and known-context citations.</p><div class="grid">'+''.join(cards)+'</div><h2>Controlled local failure exercises</h2><ul>'+''.join(failures)+'</ul><p>These checks do not establish answer correctness or citation support. Held-out responses were not selected.</p></main></html>'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(render(json.loads(args.input.read_text(encoding='utf-8'))),encoding='utf-8')
