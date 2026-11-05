"""Render actual saved HTTP observations; does not execute a server."""
import argparse
import html
import json
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();data=json.loads(a.input.read_text())
    cards=[]
    for row in data['observations']:
        body=row['body'];result=body.get('result',body)
        detail=[]
        if 'error' in body:detail.append(body['error']['code'])
        if 'cache' in body:detail.append('cache: '+body['cache'])
        if 'principal' in result:detail.append('principal: '+result['principal'])
        if 'status' in result:detail.append('result: '+result['status'])
        if 'results' in result:detail.append('eligible source IDs: '+(', '.join(x['source_id'] for x in result['results']) or 'none'))
        if 'source_id' in result:detail.append('source: '+result['source_id'])
        if 'request' in result:detail.append('collection: '+result['request']['collection'])
        evidence=result.get('evidence',[])
        if evidence:detail.append('materialized sources: '+', '.join(x['source_id'] for x in evidence))
        text=result.get('text',evidence[0]['text'] if evidence else '')
        cards.append('<article><h2>'+html.escape(row['name'].replace('_',' '))+'</h2><p class="status">HTTP '+str(row['status_code'])+'</p><p>'+html.escape(' · '.join(detail))+'</p>'+('<blockquote>'+html.escape(text)+'</blockquote>' if text else '')+'</article>')
    title='Authorize Collection Searches'
    output='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>body{margin:0;background:#fff;color:#192136;font:16px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:24px}h1{font-size:30px;line-height:1.15}h2{font-size:19px;margin:0}.intro{max-width:75ch;color:#596375}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}article{border:1px solid #dfe4ed;border-radius:8px;padding:18px;overflow-wrap:anywhere}.status{color:#274bc4;font-weight:600}blockquote{margin:12px 0 0;border-left:3px solid #274bc4;padding-left:12px}p{margin:10px 0}@media(max-width:600px){main{padding:16px}.grid{grid-template-columns:1fr}h1{font-size:27px}}</style><main><h1>'+title+'</h1><p class="intro">Actual local HTTP execution against a pinned offline corpus. Public synthetic identities and collections; no model or answer generation. This saved report makes no requests.</p><section class="grid">'+''.join(cards)+'</section></main></html>'
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(output)
if __name__=='__main__':main()
