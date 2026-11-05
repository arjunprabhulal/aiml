"""Compact actual offline controller and source-outcome summaries."""
from html import escape
import json
from pathlib import Path
import sys


def runtime_html(runtime):
    usage=runtime['usage'];limits=runtime['limits']
    body='<p><strong>Controller: '+escape(runtime['controller_status'])+'</strong> · '+escape(runtime['terminal_reason'])+'</p><p>Steps '+str(usage['steps'])+'/'+str(limits['max_steps'])+' · searches '+str(usage['searches'])+'/'+str(limits['max_searches'])+' · reads '+str(usage['reads'])+'/'+str(limits['max_reads'])+'</p><p>Reserved source-text bytes '+str(usage['reserved_source_bytes'])+'/'+str(limits['max_source_bytes'])+' · validated delivered bytes '+str(usage['delivered_source_bytes'])+'</p>'
    events=[]
    for event in runtime['trace']:
        action=event.get('action');label='action refused'
        if action:
            arguments=action['arguments'];label=action['tool']+' '+(arguments['query'] if action['tool']=='search' else arguments['handle']['source_id'])
        state=event.get('status',event['decision'])
        events.append('<li>'+escape(label)+' — '+escape(state)+(' (not invoked)' if not event['invoked'] else '')+'</li>')
    body+='<ul>'+''.join(events)+'</ul>'
    return body


def render(record,title):
    if record.get('model_called') is not False:raise ValueError('expected offline scripted record')
    sections=[]
    if 'cases' in record:
        intro='Limits admit real local tool attempts before execution. No executed model agent or generated answer.'
        for case in record['cases']:
            sections.append('<section><h2>'+escape(case['case_id'].replace('_',' '))+'</h2>'+runtime_html(case['result'])+'</section>')
        fault=record['controlled_tool_failure']
        sections.append('<section><h2>Controlled tool exception</h2><p class="note">'+escape(fault['scope'])+'</p>'+runtime_html(fault['result'])+'</section>')
    else:
        intro='Fixed pipeline versus a hand-coded conditional tool policy. Exact source-retrieval checks; no model or answer comparison.'
        summary=[]
        for name,counts in record['summary'].items():
            summary.append('<p><strong>'+escape(name)+'</strong>: '+str(counts['pass'])+' pass · '+str(counts['fail'])+' fail · '+str(counts['incomplete'])+' incomplete</p>')
        sections.append('<section><h2>All original development trials retained</h2>'+''.join(summary)+'<p class="note">Unsupported cases have no retrieval target and remain incomplete. Controller terminal states stay separate from these outcome checks.</p></section>')
        case_ids=list(dict.fromkeys(t['case_id'] for t in record['trials']))
        for case_id in case_ids:
            trials=[t for t in record['trials'] if t['case_id']==case_id]
            body='<h2>'+escape(case_id)+'</h2><p>'+escape(trials[0]['question'])+'</p>'
            for trial in trials:
                outcome=trial['outcome_check'];runtime=trial['runtime'];usage=runtime['usage']
                sources=[o['result']['source_id'] for o in runtime['observations'] if o['tool']=='read']
                body+='<article><h3>'+escape(trial['policy'])+'</h3><p><strong>Source check: '+escape(outcome['status'])+'</strong> · '+escape(outcome['reason'])+'</p><p>Controller '+escape(runtime['controller_status'])+' · policy '+escape(str(trial['policy_terminal_status']))+'</p><p>Read sources: '+escape(' → '.join(sources) or 'none')+'</p><p class="note">'+str(usage['steps'])+' actions · '+str(usage['searches'])+' searches · '+str(usage['reads'])+' reads · '+str(usage['delivered_source_bytes'])+' validated delivered text bytes</p></article>'
            sections.append('<section>'+body+'</section>')
        sections.append('<section><h2>Comparison boundaries</h2><ul>'+''.join('<li>'+escape(text)+'</li>' for text in record['confounds'])+'</ul></section>')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+escape(title)+'''</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#192136;font:18px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:28px 22px}h1{font-size:clamp(28px,4vw,40px);line-height:1.2}h2{font-size:23px;margin-top:0}h3{font-size:20px}p,li{overflow-wrap:anywhere}section{padding:20px;border:1.5px solid #192136;border-radius:10px;background:#fff;margin:18px 0}article{padding:10px 0;border-top:1px solid #dfe4ed}.mode{color:#274bc4;font-size:16px;font-weight:700}.note{font-size:16px;color:#596375}li{font-size:16px;margin:8px 0}ul{padding-left:22px}a{color:#274bc4}@media(max-width:600px){main{padding:20px 16px}section{padding:16px}}
</style></head><body><main><p class="mode">Actual local SQLite tool execution · Scripted policy · No model call</p><h1>'''+escape(title)+'''</h1><p>'''+escape(intro)+'''</p>'''+''.join(sections)+'<p class="note">'+escape(record['limit'])+'</p><p class="note">Complete bound handles, read receipts, traces and configuration remain in the raw run record linked by the lesson.</p></main></body></html>'


if __name__=='__main__':
    root=Path(__file__).parent;stamp='limits' if root.name.startswith('limit') else 'comparison'
    record=json.loads((root/f'runs/2026-10-23-{stamp}/result.json').read_text())
    target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(render(record,root.name.replace('-',' ').capitalize()),encoding='utf-8');print(target)
