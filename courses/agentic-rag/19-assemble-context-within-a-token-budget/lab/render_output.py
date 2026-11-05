"""Compact HTML summary of the actual pinned-tokenizer assembly record."""
from html import escape
import json
from pathlib import Path
import sys


def render(record):
    if record.get('model_called') is not False:raise ValueError('expected tokenizer-only record')
    cards=[]
    for name in ['roomy','tight','empty_retrieval']:
        result=record[name];counts=result['separate_text_counts']
        component_total=counts['instructions']+counts['question']+counts['kept_window_texts']
        cards.append('<article><h2>'+escape(name.replace('_',' '))+'</h2><p class="number">'+str(result['input_tokens'])+' input tokens</p><p>Input budget '+str(result['input_budget'])+' = request limit '+str(result['context_limit'])+' − reserve '+str(result['max_new_tokens'])+' − margin '+str(result['margin'])+'</p><p>'+str(len(result['kept_evidence']))+' windows kept · '+str(len(result['dropped_evidence']))+' dropped</p><p class="note">Separately counted instructions, question and kept window text: '+str(component_total)+' tokens. The complete request also includes labels, wrappers and the chat template.</p></article>')
    windows=[]
    for group in record['windows']['groups']:
        decision='kept' if group['window_id'] in record['tight']['kept_evidence'] else 'dropped'
        windows.append('<li><strong>'+escape(group['source_id'])+' · version '+escape(group['version'])+'</strong><br>'+escape(group['section_title'])+'<br>Tight-budget decision: <strong>'+decision+'</strong> · priority seed rank '+str(min(s['rank'] for s in group['seed_ranks']))+'<br>'+str(len(group['chunk_ids']))+' chunks · character span ['+str(group['start'])+', '+str(group['end'])+')<br><span class="note">Members: '+escape(', '.join(m['role'] for m in group['members']))+'<br>Window ID prefix: '+escape(group['window_id'][:12])+'…</span></li>')
    overflow=record['required_context_overflow'];boundary=record['literal_boundary']
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Context windows within a token budget — actual run</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#192136;font:18px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:28px 22px}h1{font-size:clamp(28px,4vw,40px);line-height:1.2}h2{font-size:23px;margin-top:0}p{overflow-wrap:anywhere}.mode{color:#274bc4;font-weight:700;font-size:16px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}article,section{background:#fff;border:1.5px solid #192136;border-radius:10px;padding:20px;margin:20px 0}.grid article{margin:0}.number{font-size:26px;font-weight:700}.note{font-size:15px;color:#596375}ul{padding-left:22px;display:grid;grid-template-columns:1fr 1fr;gap:20px}li{font-size:16px;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.6 ui-monospace,monospace}a{color:#274bc4}@media(max-width:650px){main{padding:20px 16px}.grid,ul{grid-template-columns:1fr}article,section{padding:16px}.grid{gap:14px}}
</style></head><body><main><p class="mode">Actual local tokenization · Pinned Gemma template · No model call</p><h1>Assemble context within a token budget</h1><p>Original synthetic Aster developer fixtures. Explicit ranked seeds become complete surrounding-context windows.</p><p>Configured limits below are test budgets, not model context capacity.</p><div class="grid">'''+''.join(cards)+'</div><section><h2>Whole-window admission</h2><p>'+escape(record['question'])+'</p><ul>'+''.join(windows)+'</ul><p class="note">Overlapping same-section seeds merge before budgeting. No half-chunk truncation. Displayed IDs are abbreviated; complete IDs and source receipts remain in the raw record.</p></section><section><h2>Required context refused</h2><p>'+escape(overflow['error'])+': required '+str(overflow['required_input_tokens'])+' tokens exceeds available '+str(overflow['available_input_tokens'])+'.</p><p>The instructions and question are retained together or the request is rejected.</p></section><section><h2>Literal boundary check</h2><p>Untrusted source literal:</p><pre>'+escape(boundary['source_literal'])+'</pre><p>Inside the serialized reference block:</p><pre>'+escape(boundary['escaped_literal'])+'</pre><p>Chat roles: '+escape(', '.join(boundary['roles']))+'</p><p class="note">'+escape(boundary['limit'])+'</p></section><p class="note">Complete serialized counts, full messages, source identities and admission traces: <a href="/examples/assemble-context-within-a-token-budget/runs/2026-10-23-budget/result.json">raw run record</a>. '+escape(record['limit'])+'</p></main></body></html>'


if __name__=='__main__':
    root=Path(__file__).parent
    record=json.loads((root/'runs/2026-10-23-budget/result.json').read_text())
    target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(render(record),encoding='utf-8');print(target)
