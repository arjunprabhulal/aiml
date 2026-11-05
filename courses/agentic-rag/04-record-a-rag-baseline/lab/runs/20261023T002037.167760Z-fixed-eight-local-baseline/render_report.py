"""Render one saved baseline summary. Never imports an inference client or runs the pipeline."""
from html import escape
from pathlib import Path
import argparse,hashlib,json
RUN=Path(__file__).resolve().parent

def read(name):return json.loads((RUN/name).read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def render():
 manifest=read('run-manifest.json')
 for name,value in manifest['artifacts'].items():
  if sha(RUN/name)!=value:raise ValueError('Saved artifact changed: '+name)
 record=read('recording.json');observations=read('case-observations.json');checks=read('automatic-contracts.json');metrics=read('measurements.json');ledger=read('http-ledger.json')
 outcomes={key:sum(s[key]for s in checks['summary'].values())for key in ['pass','fail','incomplete']}
 total=ledger['counts']['documents']+sum(ledger['counts']['queries'].values())+sum(ledger['counts']['generation'].values())
 cards=[]
 for row in metrics['rows']:
  cid=row['case_id']
  if cid not in ('utf8-write','read-newline-312','create-parents'):continue
  trial=record['responses'][cid][0];raw=observations[cid]['generation']['raw'];output=trial.get('output');check=next(c for c in checks['results']if c['case_id']==cid)
  if output:
   status='<p><strong>Saved status:</strong> <code>'+escape(output['status'])+'</code></p>'
   answer='<p class="answer"><strong>Saved model response:</strong> '+escape(output['answer'])+'</p>'
  else:
   status='<p><strong>Saved status:</strong> No parsed response</p>'
   answer='<p class="answer"><strong>Raw final content:</strong> <code>""</code></p><p>Structured-output parsing failed. No repaired answer was generated.</p>'
  targets='Unscored: unsupported question'if row['retrieval']is None else ('Target present at rank '+str(int(1/row['retrieval']['reciprocal_rank']))if row['retrieval']['hit']else'Target absent from top two')
  sources=', '.join(output.get('source_ids',[]))if output else''
  finish=raw['response_metadata'].get('done_reason')
  cards.append('<article><p class="mode">'+escape(row['split'])+' · '+escape(cid)+'</p><h2>'+escape(observations[cid]['question'])+'</h2>'+status+answer+'<p><strong>Linked sources:</strong> '+(escape(sources)or'None')+'</p><p><strong>Retrieval:</strong> '+escape(targets)+'</p><p><strong>Automatic reply checks:</strong> '+escape(check['verdict'])+'</p><p><strong>Stop reason:</strong> '+escape(str(finish))+'</p></article>')
 counts=f"{len(metrics['rows'])} fixed questions · {total} inference requests · {ledger['counts']['metadata']} local metadata request"
 summary=f"{outcomes['pass']} automatic passes · {outcomes['fail']} failures · {outcomes['incomplete']} incomplete response"
 html="""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>One local RAG baseline</title><style>*{box-sizing:border-box}body{margin:0;background:#fff;color:#192136;font:17px/1.5 Arial,sans-serif}main{max-width:1440px;margin:auto;padding:28px}h1{font-size:32px;line-height:1.2;margin:8px 0 16px}h2{font-size:21px;line-height:1.35;margin:8px 0 14px}p{margin:9px 0}.mode{color:#596375;font-size:17px}.summary{background:#dbeafe;border-left:4px solid #274bc4;padding:16px;margin:20px 0}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}article{border:1px solid #dfe4ed;border-radius:8px;padding:20px;min-width:0}.answer{border-top:1px solid #dfe4ed;padding-top:12px}code{font:17px/1.5 monospace;overflow-wrap:anywhere}footer{margin-top:24px;color:#596375}a{color:#274bc4}strong{font-weight:600}@media(max-width:900px){.cards{grid-template-columns:1fr}}@media(max-width:600px){main{padding:18px}h1{font-size:27px}h2{font-size:20px}article{padding:16px}.cards{gap:16px}.summary{padding:14px}}</style></head><body><main>"""
 html+='<p class="mode">Fresh local inference · saved-run summary · '+escape(manifest['created_at_utc'])+'</p><h1>Record a RAG Baseline</h1><p><strong>Retrieval Results, Answer Checks, and Run Settings</strong></p><p>Embeddings: qwen3-embedding:0.6b · Answers: gemma4:e2b</p><div class="summary"><p>'+escape(counts)+'</p><p><strong>'+escape(summary)+'</strong></p><p>Small public teaching set, one trial. Automatic checks are not an overall quality score. Human answer review is unreviewed.</p></div><p class="mode">Three diagnostic cases from the complete eight-question run</p><div class="cards">'+''.join(cards)+'</div>'
 html+='<footer><p>Compact saved-response summary showing three diagnostic cases; not a terminal capture or a new model run. All eight raw responses, intermediate events and wire chunks remain in the linked files.</p><p>Expected labels are evaluator inputs, not generated answers. The separate AI answer inspection does not fill the human-review template. Reasoning token counts were not supplied separately.</p><p><a href="recording.json">Raw responses and query timings</a> · <a href="http-ledger.json">Request/response streams</a> · <a href="measurements.json">Retrieval measurements</a></p></footer></main></body></html>'
 return html

def main():
 p=argparse.ArgumentParser();p.add_argument('--html',type=Path,required=True);a=p.parse_args()
 a.html.parent.mkdir(parents=True,exist_ok=True);a.html.write_text(render());print(a.html)
if __name__=='__main__':main()
