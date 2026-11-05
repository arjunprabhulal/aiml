"""Render actual saved context windows and their seed/neighbor provenance."""
import argparse
from html import escape
import json
from pathlib import Path

def render(result):
    cards=[];chunks={c['chunk_id']:c for c in result['index']['chunks']}
    for group in result['windows']['groups']:
        members=[]
        for member in group['members']:
            chunk=chunks[member['chunk_id']];rank=member['retrieval_rank']
            members.append('<section><h3>'+escape(member['role'])+(' · seed rank '+str(rank) if rank is not None else ' · no retrieval rank')+'</h3><p>Source order '+str(chunk['order'])+' · characters ['+str(chunk['start'])+', '+str(chunk['end'])+')</p><blockquote>'+escape(chunk['text'])+'</blockquote></section>')
        cards.append('<article><h2>'+escape(group['section_title'])+'</h2><p>'+escape(group['source_id'])+' · Synthetic API '+escape(group['version'])+' · '+str(len(group['chunk_ids']))+' chunks · '+str(len(group['seed_ids']))+' seeds</p>'+''.join(members)+'</article>')
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Surrounding context windows</title><style>*{box-sizing:border-box}body{margin:0;font:17px/1.5 system-ui,sans-serif;color:#192136;background:#fff}main{max-width:1100px;margin:auto;padding:32px 24px}h1{font-size:32px;margin:0 0 12px}h2{font-size:24px}h3{font-size:19px}p{margin:10px 0;overflow-wrap:anywhere}.mode{color:#596375}article{border:1.5px solid #192136;background:#dcfce7;border-radius:8px;padding:20px}section{border-top:1px solid #596375;padding:10px 0}blockquote{margin:14px 0;border-left:3px solid #274bc4;padding-left:14px;white-space:pre-wrap;overflow-wrap:anywhere}@media(max-width:700px){main{padding:24px 16px}h1{font-size:27px}article{padding:16px}}</style><main><h1>Surrounding context windows</h1><p class="mode">Actual offline expansion · Explicit controlled seeds · Original synthetic Aster API</p><p>'+str(len(result['windows']['seed_ids']))+' seeds · radius '+str(result['windows']['radius'])+' · '+str(len(result['windows']['groups']))+' merged window(s). Only current chunks in the same source revision, version and section are eligible. Neighbor passages are not retrieval hits.</p>'+''.join(cards)+'</main></html>'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(render(json.loads(args.input.read_text(encoding='utf-8'))),encoding='utf-8')
