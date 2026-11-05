"""Render actual local HTTP responses, not a fabricated terminal or API run."""
import argparse
from html import escape
import json
from pathlib import Path

def render(result):
    cards=[]
    for case in result['cases']:
        body=case['response'];status=body.get('status',body.get('error',{}).get('code'))
        extra=''
        if body.get('evidence'):
            extra='<p>Read sources: '+escape(', '.join(row['source_id'] for row in body['evidence']))+'</p>'
        if 'usage' in body:extra+='<p>Invoked steps '+str(body['usage']['steps'])+' · Delivered passage bytes '+str(body['usage']['delivered_source_bytes'])+'</p>'
        cards.append('<article><h2>'+escape(case['scenario'])+'</h2><p>HTTP <strong>'+str(case['http_status'])+'</strong> · '+escape(status)+'</p>'+extra+'</article>')
    fault=result['trusted_fault'];shutdown=all(result[name]['shutdown_complete_observed'] and result[name]['server_process_reaped'] for name in ['lifecycle','fault_lifecycle'])
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Local FastAPI retrieval</title><style>*{box-sizing:border-box}body{margin:0;font:17px/1.5 system-ui,sans-serif;background:#fff;color:#192136}main{max-width:1100px;margin:auto;padding:32px 24px}h1{font-size:32px;margin:0 0 12px}h2{font-size:21px;margin:0 0 12px}p{margin:10px 0;overflow-wrap:anywhere}.mode{color:#596375}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}article{border:1.5px solid #192136;border-radius:8px;background:#dcfce7;padding:18px}.fault{background:#ffe4e6;border-style:dashed;border-color:#b91c1c;margin-top:16px}@media(max-width:800px){main{padding:24px 16px}.grid{grid-template-columns:1fr}h1{font-size:27px}}</style><main><h1>Local FastAPI retrieval</h1><p class="mode">Actual Uvicorn + HTTPX over loopback · Scripted retrieval · No model generation</p><p>Request validation, pre-action limits and exact passage bindings. Completed means a configured context marker was found; no generated answer or quality improvement is claimed.</p><div class="grid">'+''.join(cards)+'</div><article class="fault"><h2>Trusted controlled tool failure</h2><p>HTTP '+str(fault['http_status'])+' · '+escape(fault['response']['status'])+' · Private exception details withheld</p><p>Application shutdown observed and child processes reaped: '+str(shutdown).lower()+'</p></article></main></html>'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(render(json.loads(args.input.read_text(encoding='utf-8'))),encoding='utf-8')
