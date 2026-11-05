"""Render actual controlled source-span observations from saved run JSON."""
import argparse
from html import escape
import json
from pathlib import Path

def render(result):
    cards=[]
    for comparison in result['comparisons']:
        index=result['indexes'][comparison['strategy']]
        selected=[c for c in index['chunks'] if c['chunk_id'] in comparison['instruction_containing_chunk_ids']]
        cards.append('<article><h2>'+escape(comparison['strategy'])+'</h2><p><strong>'+str(comparison['chunk_count'])+' chunks</strong> across both documents</p><p>Instruction and qualifier in one chunk: <strong>'+str(comparison['instruction_and_qualifier_share_chunk']).lower()+'</strong></p>'+''.join('<p>Instruction chunk · characters ['+str(c['start'])+', '+str(c['end'])+')</p><blockquote>'+escape(c['text'])+'</blockquote>' for c in selected)+'</article>')
    return page('Chunk boundaries in developer documents','Actual offline source processing · Original synthetic Aster API fixture', '<p>Controlled instruction span '+escape(str(result['comparisons'][0]['instruction_span']))+', qualifier span '+escape(str(result['comparisons'][0]['qualifier_span']))+'. Half-open character offsets refer to normalized source text. No embeddings or semantic-quality claim.</p><div class="grid">'+''.join(cards)+'</div><p>Fixed-character chunks use 80 characters; heading-aware packing targets 220 characters and preserves whole oversized paragraphs. All three policies stay within a heading section.</p>')

def page(title,subtitle,body):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>'+escape(title)+'</title><style>*{box-sizing:border-box}body{margin:0;font:17px/1.5 system-ui,sans-serif;color:#192136;background:#fff}main{max-width:1100px;margin:auto;padding:32px 24px}h1{font-size:32px;margin:0 0 12px}h2{font-size:23px;margin:0 0 12px}p{margin:10px 0;overflow-wrap:anywhere}.mode{color:#596375}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}article{border:1.5px solid #192136;border-radius:8px;padding:18px;background:#fef3c7}blockquote{margin:16px 0;padding-left:12px;border-left:3px solid #274bc4;white-space:pre-wrap;overflow-wrap:anywhere}@media(max-width:800px){main{padding:24px 16px}.grid{grid-template-columns:1fr}h1{font-size:27px}}</style><main><h1>'+escape(title)+'</h1><p class="mode">'+escape(subtitle)+'</p>'+body+'</main></html>'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(render(json.loads(args.input.read_text(encoding='utf-8'))),encoding='utf-8')
