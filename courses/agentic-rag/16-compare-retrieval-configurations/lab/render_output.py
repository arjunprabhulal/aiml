"""Render actual recorded local retrieval results; no new retrieval execution."""
from html import escape
import json
from pathlib import Path
import sys


def ranking(rows):
    return '<ol>'+''.join('<li><strong>'+escape(row['source_id'])+'</strong> · coverage '+escape(str(row['coverage_score']))+' · incoming rank '+str(row['incoming_rank'])+'<p>'+escape(row['text'])+'</p><p class="trace">Matched tokens: '+escape(', '.join(row['rerank_features']['matched_tokens']))+'<br>Query tokens: '+escape(', '.join(row['rerank_features']['query_tokens']))+'<br>Original lexical/vector ranks: '+escape(str(row.get('lexical_rank')))+' / '+escape(str(row.get('vector_rank')))+'<br>Native lexical/vector scores: '+escape(str(row.get('lexical_score')))+' / '+escape(str(row.get('vector_score')))+'<br>RRF score: '+escape(str(row.get('fused_score')))+'</p></li>' for row in rows)+'</ol>'


def render(record,title):
    if record.get('model_called') is not False:raise ValueError('expected offline run')
    sections=[]
    if 'development_cases' in record:
        intro='Transparent deterministic token coverage. Not a learned reranker or cross-encoder.'
        for case in record['development_cases']:
            before=' → '.join(row['source_id'] for row in case['before'])
            sections.append('<section><h2>'+escape(case['case_id'])+'</h2><p>'+escape(case['query'])+'</p><p>Incoming RRF order: '+escape(before)+'</p>'+ranking(case['after'])+'</section>')
        check=record['mechanism_check']
        sections.append('<section><h2>Controlled candidate-order contract check</h2><p>'+escape(check['scope'])+'</p><p>'+escape(check['query'])+'</p><p>Deliberately reversed input: '+escape(' → '.join(r['source_id'] for r in check['before']))+'</p>'+ranking(check['after'])+'</section>')
        sections.append('<section><h2>Altered candidate refused</h2><p>'+escape(record['altered_candidate_refusal'])+'</p><p>Empty candidate input returned '+str(len(record['empty_candidates']))+' rows.</p></section>')
    else:
        intro='Frozen lexical, vector, RRF and RRF plus transparent coverage configurations. Labels join after retrieval.'
        body=[]
        for name,cutoffs in record['aggregate'].items():
            for cutoff,metric in cutoffs.items():
                body.append('<tr><th>'+escape(name)+'</th><td>'+cutoff+'</td><td>'+str(metric['mean_recall_at_k'])+'</td><td>'+str(metric['mean_reciprocal_rank_at_k'])+'</td></tr>')
        sections.append('<section><h2>Supported development cases only</h2><p>'+str(record['supported_case_count'])+' supported cases. '+str(record['unsupported_case_count'])+' unsupported case excluded from means.</p><div class="table"><table><thead><tr><th>Configuration</th><th>k</th><th>Mean recall@k</th><th>Mean reciprocal rank@k</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div></section>')
        for case in record['per_query']:
            rows=[]
            for name,cutoffs in case['configurations'].items():
                metric=cutoffs['1'];rows.append('<tr><th>'+escape(name)+'</th><td>'+escape(str(metric['target_ranks']))+'</td><td>'+escape(str(metric['recall_at_k']))+'</td></tr>')
            sections.append('<section><h2>'+escape(case['case_id'])+'</h2><p>Supplied class: '+escape(case['case_class'])+'</p><table><thead><tr><th>Configuration</th><th>Target ranks</th><th>Recall@1</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></section>')
        for case in record['unsupported_candidate_behavior']:
            sections.append('<section><h2>Unsupported candidate behavior</h2><p>'+escape(case['case_id'])+'</p><p>'+escape(', '.join(name+': '+str(count)+' candidates' for name,count in case['returned_candidate_counts'].items()))+'</p><p>No target means null metrics. These returned candidates do not establish that the question is answerable.</p></section>')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+escape(title)+'''</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#192136;font:18px/1.55 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:36px 24px}h1{font-size:clamp(28px,4vw,42px);line-height:1.2}h2{font-size:24px}section{padding:22px;border:1.5px solid #192136;border-radius:10px;background:#fff;margin:22px 0}.mode{color:#274bc4;font-weight:700}.trace{font-size:15px;color:#596375;overflow-wrap:anywhere}li{padding:12px 0;border-bottom:1px solid #dfe4ed}p{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;font-size:16px;table-layout:fixed}th,td{text-align:left;padding:9px;border-bottom:1px solid #dfe4ed;overflow-wrap:anywhere}.note{color:#596375}@media(max-width:500px){main{padding:22px 16px}section{padding:16px}table{font-size:12px}th,td{padding:5px}ol{padding-left:22px}}
</style></head><body><main><p class="mode">Actual local retrieval execution · Saved vector replay · No model call</p><h1>'''+escape(title)+'''</h1><p>'''+escape(intro)+'''</p><p>The four original development cases show no observed ranking gain from coverage reranking. The UTF-8 read/write failure remains.</p>'''+''.join(sections)+'<p class="note">'+escape(record['limit'])+'</p></main></body></html>'


if __name__=='__main__':
    root=Path(__file__).parent;stamp='rerank' if root.name.startswith('rerank') else 'compare'
    record=json.loads((root/f'runs/2026-10-23-{stamp}/result.json').read_text())
    target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(render(record,root.name.replace('-',' ').capitalize()),encoding='utf-8');print(target)
