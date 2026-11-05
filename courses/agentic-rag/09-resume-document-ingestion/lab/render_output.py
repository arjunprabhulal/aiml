"""Render recorded SQLite maintenance operations; no simulated terminal output."""
from html import escape
import json
from pathlib import Path
import sys


def render(record, title):
    if record['execution_mode']!='offline-sqlite-source-maintenance' or record['model_called'] is not False:
        raise ValueError('expected offline SQLite maintenance record')
    cards=[]
    for step in record['steps']:
        parts=[f'<h2>{escape(step["operation"])}</h2>']
        for key in ['status','error','source_id','outcome','query']:
            if key in step:parts.append(f'<p><strong>{escape(key)}:</strong> {escape(str(step[key]))}</p>')
        if 'actions' in step:
            parts.append('<ul>'+''.join(f'<li>{escape(a["source_id"])}: {escape(a["action"])}</li>' for a in step['actions'])+'</ul>')
        if 'matches' in step:
            parts.append(f'<p><strong>Actual MATCH rows: {len(step["matches"])}</strong></p>')
            for match in step['matches']:
                parts.append(f'<p>{escape(match["source_id"])}</p><pre>{escape(match["text"])}</pre><p class="hash">Chunk ID: {escape(match["chunk_id"])}</p>')
        if 'retired_chunk_ids' in step:
            parts.append('<p>Retired chunk IDs</p><pre>'+escape('\n'.join(step['retired_chunk_ids']))+'</pre>')
        state=step.get('state',{})
        parts.append('<p class="counts">'+ ' · '.join(f'{escape(table)}: {len(rows)} rows' for table,rows in state.items())+'</p>')
        if 'checkpoints' in state:
            parts.append('<p>Committed checkpoint sources: '+escape(', '.join(row[1] for row in state['checkpoints']))+'</p>')
        cards.append('<section>'+''.join(parts)+'</section>')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+escape(title)+'''</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#192136;font:18px/1.55 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:36px 24px}h1{font-size:clamp(28px,4vw,42px);line-height:1.2}h2{font-size:23px;overflow-wrap:anywhere}section{padding:22px;border:1.5px solid #192136;border-radius:10px;background:#fff;margin:22px 0}pre,.hash{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;font:15px/1.6 ui-monospace,monospace}.mode{color:#274bc4;font-weight:700}.counts,.note{color:#596375}@media(max-width:500px){main{padding:22px 16px}section{padding:16px}}
</style></head><body><main><p class="mode">Actual recorded SQLite execution · Offline · No model call</p><h1>'''+escape(title)+'''</h1><p>Persistent local database operations and observed row states. The raw JSON contains complete table rows.</p>'''+''.join(cards)+'''<p class="note">No dense-vector, answer-quality, secure-erasure or throughput measurement. Raw record: runs/2026-10-23-maintenance/run.json.</p></main></body></html>'''


if __name__=='__main__':
    root=Path(__file__).parent
    record=json.loads((root/'runs/2026-10-23-maintenance/run.json').read_text())
    output=Path(sys.argv[1]);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(render(record, root.name.replace('-',' ').capitalize()),encoding='utf-8')
    print(output)
