"""Render the complete actual scripted search/read sequence from saved data."""
import argparse
from html import escape
import json
from pathlib import Path

def render(result):
    controller=result['controller'];cards=[]
    for index,observation in enumerate(controller['observations'],1):
        if observation['tool']=='search':
            payload=observation['result'];body='<p>Query <strong>'+escape(payload['query'])+'</strong> · Python '+escape(payload['version'])+'</p><p>Returned source IDs: '+escape(', '.join(r['source_id'] for r in payload['results']) or 'none')+'</p>'
        else:
            payload=observation['result'];body='<p>'+escape(payload['source_id'])+' · Python '+escape(payload['version'])+' · '+str(payload['byte_count'])+' UTF-8 passage bytes</p><blockquote>'+escape(payload['text'])+'</blockquote>'
        cards.append('<article><h2>'+str(index)+'. '+escape(observation['tool'])+'</h2>'+body+'</article>')
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Scripted query refinement</title><style>*{box-sizing:border-box}body{margin:0;font:17px/1.5 system-ui,sans-serif;color:#192136;background:#fff}main{max-width:1100px;margin:auto;padding:32px 24px}h1{font-size:32px;margin:0 0 12px}h2{font-size:23px}p{overflow-wrap:anywhere}.mode{color:#596375}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}article{border:1.5px solid #192136;border-radius:8px;background:#dcfce7;padding:18px}blockquote{border-left:3px solid #274bc4;padding-left:14px;margin:16px 0;overflow-wrap:anywhere}@media(max-width:700px){main{padding:24px 16px}.grid{grid-template-columns:1fr}h1{font-size:27px}}</style><main><h1>Scripted query refinement</h1><p class="mode">Actual local tools · Handwritten rule controller · No model execution</p><p>Original question: '+escape(controller['question'])+'</p><p>Declared passage marker: <strong>'+escape(controller['policy']['required_marker'])+'</strong>. This literal check finds context; it does not evaluate answer quality.</p><div class="grid">'+''.join(cards)+'</div><p>Status: <strong>'+escape(controller['status'])+'</strong> · '+escape(controller['reason'])+'</p><p>Controlled duplicate-query stop: <strong>'+escape(result['controlled_duplicate_stop']['reason'])+'</strong></p></main></html>'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(render(json.loads(args.input.read_text(encoding='utf-8'))),encoding='utf-8')
