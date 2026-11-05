"""Render the actual saved SQLite ranking; never fabricate terminal output."""
import argparse
from html import escape
import json
from pathlib import Path

def render(result):
    cards=[]
    for query in result['queries']:
        rows=[]
        for rank,row in enumerate(query['results'],1):
            rows.append('<li><strong>'+str(rank)+'. '+escape(row['source_id'])+'</strong><p>Python '+escape(row['version'])+' · Native score <code>'+format(row['native_score'],'.12g')+'</code></p><p>Term frequency '+str(row['term_frequency'])+' · Document length '+str(row['document_length'])+' tokens</p></li>')
        cards.append('<article><h2>'+escape(query['query'] or '(empty query)')+'</h2><p>Status: '+escape(query['status'])+'</p><ol>'+''.join(rows)+'</ol></article>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Native BM25 ranking</title><style>*{box-sizing:border-box}body{margin:0;font:17px/1.5 system-ui,sans-serif;color:#192136;background:#fff}main{max-width:1100px;margin:auto;padding:32px 24px}h1{font-size:32px;margin:0 0 12px}h2{font-size:23px;margin:0 0 10px}p{margin:8px 0}.mode{color:#596375}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}article{border:1.5px solid #192136;background:#dcfce7;border-radius:8px;padding:18px}ol{list-style:none;padding:0;margin:0}li{border-top:1px solid #596375;padding:12px 0}code{font-size:16px;overflow-wrap:anywhere}@media(max-width:700px){main{padding:24px 16px}.grid{grid-template-columns:1fr}h1{font-size:27px}}</style><main><h1>Native BM25 ranking</h1><p class="mode">Actual executed SQLite FTS5 search · Offline · No model inference</p><p>Four original Python API summaries. Lower native scores rank first; chunk IDs break ties. A lexical match does not establish answer correctness.</p><div class="grid">'''+''.join(cards)+'</div><p>Rejected syntax queries: '+str(len(result['rejected_queries']))+'. Indexed tokenizer terms: '+str(len(result['indexed_terms']))+'.</p></main></html>'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(render(json.loads(args.input.read_text(encoding='utf-8'))),encoding='utf-8')
if __name__=='__main__':main()
