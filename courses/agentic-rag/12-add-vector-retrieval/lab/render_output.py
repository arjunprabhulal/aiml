"""Render the recorded retriever output without executing queries or models."""
from html import escape
import json
from pathlib import Path
import sys


def rows_html(rows,score_key):
    parts=[]
    for row in rows:
        score=row.get(score_key)
        parts.append('<article><p><strong>'+escape(row['source_id'])+'</strong> · Python '+escape(row['version'])+' · '+escape(score_key)+' '+escape(str(score))+'</p><p>'+escape(row['text'])+'</p><p class="hash">Chunk ID: '+escape(row['chunk_id'])+'</p></article>')
    return ''.join(parts) or '<p>No returned rows.</p>'


def render(record,title):
    if record.get('model_called') is not False:raise ValueError('expected offline replay')
    sections=[]
    if 'development_cases' in record:
        for case in record['development_cases']:
            sections.append('<section><h2>'+escape(case['case_id'])+'</h2><p>'+escape(case['query'])+'</p><p>Requested Python version: '+escape(case['requested_version'])+' · supplied case class: '+escape(case['case_class'])+'</p>'+rows_html(case['results'],'score')+'</section>')
        refusal=record['unknown_query_refusal']
    else:
        for step in record['steps']:
            version=step['policy']['version']['$eq']
            sections.append('<section><h2>Version equals '+escape(version)+'</h2><p>Allowed candidate chunks: '+str(len(step['candidate_chunk_ids']))+'</p><h3>Vector query</h3><p>'+escape(step['vector_query'])+'</p>'+rows_html(step['vector_results'],'score')+'<h3>Lexical query</h3><p>'+escape(step['lexical_query'])+'</p>'+rows_html(step['lexical_results'],'native_score')+'</section>')
        comparison=record['prefilter_comparison']
        sections.append('<section><h2>Filter before selecting one result</h2><p>Requested version: '+escape(comparison['policy']['version']['$eq'])+'</p><p>Vector query: '+escape(comparison['vector_query'])+'</p><p>Lexical query: '+escape(comparison['lexical_query'])+'</p><table><thead><tr><th>Retriever</th><th>Filter after top 1</th><th>Filter before top 1</th></tr></thead><tbody>'+''.join('<tr><td>'+name+'</td><td>'+str(len(comparison[prefix+'_postfilter_top1']))+' rows</td><td>'+str(len(comparison[prefix+'_prefilter_top1']))+' rows</td></tr>' for name,prefix in [('Vector','vector'),('Lexical','lexical')])+'</tbody></table></section>')
        refusal=record['invalid_operator_refusal']
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+escape(title)+'''</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#192136;font:18px/1.55 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:36px 24px}h1{font-size:clamp(28px,4vw,42px);line-height:1.2}h2{font-size:24px}h3{font-size:21px}section{padding:22px;border:1.5px solid #192136;border-radius:10px;background:#fff;margin:22px 0}article{padding:14px 0;border-top:1px solid #dfe4ed}.hash{font:14px/1.6 ui-monospace,monospace;overflow-wrap:anywhere}.mode{color:#274bc4;font-weight:700}.note{color:#596375}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #dfe4ed}@media(max-width:500px){main{padding:22px 16px}section{padding:16px}table{font-size:14px}th,td{padding:6px}}
</style></head><body><main><p class="mode">Actual framework execution · Preserved vector replay · No model call</p><h1>'''+escape(title)+'''</h1><p>Real LangChain InMemoryVectorStore queries use saved Qwen embeddings. This report shows vector retrieval only.</p>'''+''.join(sections)+'<section><h2>Rejected input</h2><p>'+escape(refusal)+'</p></section><p class="note">Similarity is not correctness. This tiny development corpus does not measure search quality. No new embedding or answer generation occurred. Raw record: runs/2026-10-23-replay/run.json.</p></main></body></html>'


if __name__=='__main__':
    root=Path(__file__).parent;record=json.loads((root/'runs/2026-10-23-replay/run.json').read_text())
    target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(render(record,root.name.replace('-',' ').capitalize()),encoding='utf-8');print(target)
