"""Render a compact summary of the actual reranking record."""
from html import escape
import json
from pathlib import Path
import sys


def candidates(rows):
    items=[]
    for row in rows:
        features=row['rerank_features']
        items.append('<li><strong>'+escape(row['source_id'])+'</strong><br>Reranked '+str(row['rerank_rank'])+' · incoming '+str(row['incoming_rank'])+' · coverage '+str(features['matched_count'])+'/'+str(features['query_token_count'])+'<br><span class="tokens">Matched: '+escape(', '.join(features['matched_tokens']) or 'none')+'</span></li>')
    return '<ol>'+''.join(items)+'</ol>'


def render(record):
    if record.get('model_called') is not False:raise ValueError('expected offline reranking record')
    sections=[]
    for index,case in enumerate(record['development_cases']):
        body='<h2>'+escape(case['case_id'])+'</h2><p>'+escape(case['query'])+'</p><p class="note">Incoming order: '+escape(' → '.join(row['source_id'] for row in case['before']))+'</p>'+candidates(case['after'])
        if index==0:
            body+='<h3>Read/write failure remains</h3><p>Both passages match the same number of distinct query tokens. The incoming read passage stays first.</p>'
            for row in case['after']:
                if row['source_id'] in ('path-read','path-write'):
                    body+='<blockquote><strong>'+escape(row['source_id'])+'</strong><p>'+escape(row['text'])+'</p></blockquote>'
        sections.append('<section>'+body+'</section>')
    check=record['mechanism_check']
    sections.append('<section><h2>Controlled order check</h2><p>'+escape(check['scope'])+'</p><p>'+escape(check['query'])+'</p><p class="note">Reversed input: '+escape(' → '.join(row['source_id'] for row in check['before']))+'</p>'+candidates(check['after'])+'</section>')
    sections.append('<section><h2>Input boundaries</h2><p>Altered candidate: '+escape(record['altered_candidate_refusal'])+'</p><p>Empty input: '+str(len(record['empty_candidates']))+' rows.</p></section>')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rerank retrieved passages — actual run summary</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#192136;font:18px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:28px 22px}h1{font-size:clamp(28px,4vw,40px);line-height:1.2}h2{font-size:23px;margin:0 0 12px}h3{font-size:20px}p{margin:10px 0;overflow-wrap:anywhere}section{padding:20px;border:1.5px solid #192136;border-radius:10px;background:#fff;margin:20px 0}ol{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;padding-left:24px;margin:14px 0}li{padding-right:8px;font-size:16px;overflow-wrap:anywhere}.tokens,.note{font-size:15px;color:#596375}blockquote{margin:14px 0;border-left:3px solid #274bc4;padding-left:14px;font-size:16px}.mode{color:#274bc4;font-weight:700;font-size:16px}a{color:#274bc4}@media(max-width:600px){main{padding:20px 16px}section{padding:16px}ol{grid-template-columns:1fr;gap:12px}li{font-size:16px}}
</style></head><body><main><p class="mode">Actual local execution · Preserved vector replay · No model call</p><h1>Rerank retrieved passages</h1><p>Deterministic token coverage. No learned reranker or cross-encoder.</p><p>This summary shows candidate positions and matched-token features. All four original development orders remain unchanged.</p>'''+''.join(sections)+'''<p class="note">Full original ranks, native scores, token lists and passage text remain in the <a href="/examples/rerank-retrieved-passages/runs/2026-10-23-rerank/result.json">complete raw run record</a>. The controlled order check is not an evaluation case or a quality gain.</p></main></body></html>'''


if __name__=='__main__':
    root=Path(__file__).parent
    record=json.loads((root/'runs/2026-10-23-rerank/result.json').read_text())
    target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(render(record),encoding='utf-8');print(target)
