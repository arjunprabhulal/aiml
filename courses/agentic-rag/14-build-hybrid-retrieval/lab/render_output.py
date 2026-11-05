"""Render actual recorded local hybrid retrieval results, not a terminal mockup."""
import argparse
from html import escape
import json
from pathlib import Path

def render(result):
    cards=[]
    for case in result['development_cases']:
        rows=[]
        for row in case['results']:
            rows.append('<li><strong>'+escape(row['source_id'])+'</strong><p>BM25 rank '+str(row['lexical_rank'])+' · Vector rank '+str(row['vector_rank'])+'</p><p>Contributions '+format(row['lexical_contribution'],'.8f')+' + '+format(row['vector_contribution'],'.8f')+' = <strong>'+format(row['fused_score'],'.8f')+'</strong></p><p>Native BM25 '+str(row['lexical_score'])+'<br>Native cosine '+str(row['vector_score'])+'</p></li>')
        cards.append('<article><h2>'+escape(case['case_id'])+'</h2><p>'+escape(case['query'])+'</p><p>Requested Python '+escape(case['policy']['version']['$eq'])+'</p><ol>'+''.join(rows)+'</ol></article>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Hybrid retrieval results</title><style>*{box-sizing:border-box}body{margin:0;font:17px/1.5 system-ui,sans-serif;background:#fff;color:#192136}main{max-width:1100px;margin:auto;padding:32px 24px}h1{font-size:32px;margin:0 0 12px}h2{font-size:23px;margin:0 0 10px}p{margin:8px 0;overflow-wrap:anywhere}.mode{color:#596375}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}article{background:#dcfce7;border:1.5px solid #192136;border-radius:8px;padding:18px}ol{padding:0;list-style:none}li{border-top:1px solid #596375;padding:12px 0}@media(max-width:700px){main{padding:24px 16px}.grid{grid-template-columns:1fr}h1{font-size:27px}}</style><main><h1>Hybrid retrieval results</h1><p class="mode">Preserved-vector replay · Actual local SQLite, LangChain cosine and RRF · No model inference</p><p>Four development questions. Candidate budget 3 per branch, top-k 2, rank constant 60. Fused scores sum reciprocal ranks; native scores stay separate. Candidates do not prove an answer is supported.</p><div class="grid">'''+''.join(cards)+'</div></main></html>'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(render(json.loads(args.input.read_text(encoding='utf-8'))),encoding='utf-8')
