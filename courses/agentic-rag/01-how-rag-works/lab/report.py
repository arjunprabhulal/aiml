"""Render actual saved local model output as an inspectable, offline HTML report."""
from html import escape
import json
from pathlib import Path
import re

ROOT=Path(__file__).parent
RUN=ROOT/'runs'/'2026-10-22-concept'

def render(record: dict, test_output: str) -> str:
    names=list(record['models'])
    embedding_model=next((name for name in names if 'embedding' in name), None)
    answer_models=[name for name in names if name != embedding_model]
    if embedding_model is None or len(answer_models)!=1:
        raise ValueError('Record must identify one embedding model and one answer model.')
    answer_model=answer_models[0]
    cards=[]
    for row in record['results']:
        links=''.join(f'<li><a href="{escape(url,quote=True)}">{escape(url)}</a></li>'for url in row['source_links'])
        cards.append(f'<article><h2>{escape(row["question"])}</h2><p class="meta">Retrieved: {escape(", ".join(row["context_ids"]))}</p><p class="status">{escape(row["status"])}</p><p class="answer">{escape(row["answer"])}</p><ul>{links}</ul></article>')
    count=re.search(r'Ran (\d+) tests',test_output)
    tests=f'{count[1]} offline tests completed: OK'if count and test_output.strip().endswith('OK')else'Open the test log for its actual result.'
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><title>How RAG Works — local run report</title><style>
body{margin:0;background:#ffffff;color:#192136;font:20px/1.55 Arial,sans-serif}main{max-width:1180px;margin:48px auto;padding:0 36px}h1{font-size:38px;line-height:1.15;margin:12px 0}h2{font-size:25px;line-height:1.3;margin:0 0 12px}.mode{font-size:17px;font-weight:700;color:#274bc4}.meta,footer{color:#596375;font-size:17px}.description{max-width:1000px}article{background:#fff;border:1px solid #dfe4ed;border-radius:8px;padding:26px 30px;margin:22px 0}.status{font:700 17px/1.5 monospace;color:#274bc4}.answer{margin:16px 0;overflow-wrap:anywhere}a{color:#274bc4;overflow-wrap:anywhere}ul{padding-left:22px;font-size:17px}.checks{font-size:17px;border-top:1px solid #dfe4ed;padding-top:20px}code{font-size:17px}@media(max-width:600px){body{font-size:18px}main{margin:24px auto;padding:0 16px}h1{font-size:30px}h2{font-size:23px}article{padding:18px}.meta,footer{font-size:16px}}</style><main>
<p class="mode">Saved local model run</p><h1>How RAG Works</h1><p class="description">Actual answers from the local Qwen/Gemma run. This report displays the saved results; opening it does not make a new model call.</p>'''+f'<p class="meta">Recorded: {escape(record["recorded_on"])} · Answer model: {escape(answer_model)} · Embeddings: {escape(embedding_model)}<br>Source collection: data/docs.json · {len(record["embeddings"]["documents"])} original Python API summaries</p>'+''.join(cards)+f'<p class="checks">{escape(tests)} · Tests check replay, source IDs and empty-context handling; they do not establish general answer accuracy.</p><footer><a href="recorded-run.json">Raw local run JSON</a> · <a href="test-output.txt">Actual test log</a><p>{escape(record["run_scope"])}</p></footer></main></html>'

if __name__=='__main__':
    record=json.loads((RUN/'recorded-run.json').read_text())
    (RUN/'report.html').write_text(render(record,(RUN/'test-output.txt').read_text()))
    print('Saved local model run report:',RUN/'report.html')
