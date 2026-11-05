"""Render actual saved comparison data without running retrieval."""
import argparse
import html
import json
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();comparison=json.loads(a.input.read_text())['comparison'];cards=[]
    for row in comparison['per_case']:
        lines=['comparison: '+row['comparison']]
        if row['comparison']=='paired-supported':
            for side in ['before','after']:
                m=row[side]['metrics']['1'];lines.append(side+': target ranks '+str(m['target_ranks'])+'; recall@1 '+str(m['recall_at_k'])+'; target denominator '+str(m['target_count']))
        else:lines.append('metrics: null; '+row['after'].get('reason','unsupported question excluded'))
        cards.append('<article><h2>'+html.escape(row['case_id'])+'</h2>'+''.join('<p>'+html.escape(line)+'</p>' for line in lines)+'</article>')
    result='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Run RAG Evals on an Updated Corpus</title><style>body{margin:0;color:#192136;background:white;font:16px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:24px}h1{font-size:30px;line-height:1.15}h2{font-size:20px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}article{border:1px solid #dfe4ed;border-radius:8px;padding:18px;overflow-wrap:anywhere}.notice{border-left:3px solid #274bc4;padding-left:16px}p{margin:10px 0}@media(max-width:600px){main{padding:16px}.grid{grid-template-columns:1fr}h1{font-size:27px}}</style><main><h1>Run RAG Evals on an Updated Corpus</h1><p>Actual offline SQLite FTS5. Fixed development questions; no model or answer generation.</p><p class="notice">Synthetic update: retain the write summary, append non-factual length padding and delete the JSON summary. Stale labels are refused before explicit reannotation. No quality gain claimed.</p><section class="grid">'+''.join(cards)+'</section><p>Paired supported-case denominator: '+str(comparison['paired_aggregate']['1']['paired_supported_denominator'])+'. Deleted targets remain not comparable; unsupported metrics remain null.</p></main></html>'
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(result)
if __name__=='__main__':main()
