"""Render a compact summary of the actual synthetic directive-gate run."""
from html import escape
import json
from pathlib import Path
import sys


def render(record):
    if record.get('model_called') is not False:raise ValueError('expected offline gate record')
    cards=[]
    for case in record['cases']:
        result=case['result'];ready=result['answer_request'] is not None
        body='<h2>'+escape(case['case_id'].replace('-',' '))+'</h2><p class="status">'+escape(result['status'])+' · '+('request prepared; no model call' if ready else 'request withheld')+'</p><p>Requested version '+escape(case['requested_version'])+' · claim '+escape(case['claim_key'])+'</p><p class="note">'+escape(result['reason'])+'</p>'
        if result.get('excluded_wrong_version_ids'):
            body+='<p>Wrong-version sources excluded: '+escape(', '.join(result['excluded_wrong_version_ids']))+'</p>'
        for claim in result.get('claims',[]):
            body+='<blockquote><strong>'+escape(claim['source_id'])+' · version '+escape(claim['version'])+'</strong><p><code>'+escape(claim['quote'])+'</code></p><p class="note">Line '+str(claim['start_line'])+' · character span ['+str(claim['start'])+', '+str(claim['end'])+')</p></blockquote>'
        if result.get('missing_claim_source_ids'):
            body+='<p>Requested claim missing: '+escape(', '.join(result['missing_claim_source_ids']))+'</p>'
        if result.get('error'):body+='<p>Typed refusal: '+escape(result['error'])+'</p>'
        cards.append('<section>'+body+'</section>')
    changed=record['changed_source']
    cards.append('<section><h2>Changed pinned source</h2><p class="status">'+escape(changed['status'])+' · request withheld</p><p>'+escape(changed['error'])+': '+escape(changed['reason'])+'</p><p class="note">A temporary source copy was changed after pinning. The original fixture was preserved.</p></section>')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Conflicting documentation — actual gate run</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#192136;font:18px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:28px 22px}h1{font-size:clamp(28px,4vw,40px);line-height:1.2}h2{font-size:23px;margin:0 0 12px}p{margin:10px 0;overflow-wrap:anywhere}section{padding:20px;border:1.5px solid #192136;border-radius:10px;background:#fff;margin:18px 0}.mode,.status{color:#274bc4;font-weight:700}.mode,.note{font-size:16px}.note{color:#596375}blockquote{margin:14px 0;border-left:3px solid #274bc4;padding-left:14px;font-size:16px;overflow-wrap:anywhere}code{font:16px/1.6 ui-monospace,monospace;overflow-wrap:anywhere}a{color:#274bc4}@media(max-width:600px){main{padding:20px 16px}section{padding:16px}}
</style></head><body><main><p class="mode">Actual offline gate execution · No model call</p><h1>Handle conflicting documentation</h1><p>Original synthetic Quill developer fixtures. Explicit directive grammar only; no arbitrary prose contradiction detection.</p><p>Exact version first. Same-version disagreement withholds the request; no newest-source winner is invented.</p>'''+''.join(cards)+'<p class="note">Complete source hashes, revisions, quotes, spans and prepared request messages: <a href="/examples/handle-conflicting-documentation/runs/2026-10-23-conflicts/result.json">raw run record</a>. '+escape(record['limit'])+'</p></main></body></html>'


if __name__=='__main__':
    root=Path(__file__).parent
    record=json.loads((root/'runs/2026-10-23-conflicts/result.json').read_text())
    target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(render(record),encoding='utf-8');print(target)
