"""Render actual SDK/client observations without rerunning the MCP server."""
from html import escape
import json
from pathlib import Path
import sys


def render(record):
    if record.get('model_called') is not False:raise ValueError('expected no-model SDK record')
    initialized=record['initialization'];rows=[]
    for call in record['calls']:
        result=call['result'];error=result.get('isError',False);data=result.get('structuredContent')
        detail=''
        if error:
            detail=result['content'][0]['text'].split('\n')[0]
        elif call['tool']=='search_documentation':
            detail=str(len(data['results']))+' handles · version '+data['version']
        else:detail=data['source_id']+' · '+str(data['byte_count'])+' UTF-8 text bytes'
        rows.append('<li><strong>'+escape(call['case_id'])+'</strong><br>'+escape(call['tool'])+' · isError '+str(error).lower()+'<br><span class="note">'+escape(detail)+'</span></li>')
    read=record['validated_read']
    methods=[f['message'].get('method') for f in record['protocol_transcript'] if f['direction']=='client_to_server']
    tools=', '.join(tool['name'] for tool in record['tools']['tools'])
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Retrieval tools through MCP — actual SDK run</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#192136;font:18px/1.5 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:28px 22px}h1{font-size:clamp(28px,4vw,40px);line-height:1.2}h2{font-size:23px}section{background:#fff;border:1.5px solid #192136;border-radius:10px;padding:20px;margin:18px 0}p,li{overflow-wrap:anywhere}.mode{color:#274bc4;font-size:16px;font-weight:700}.note{font-size:16px;color:#596375}ul{padding-left:22px;display:grid;grid-template-columns:1fr 1fr;gap:18px}li{font-size:16px}blockquote{border-left:3px solid #274bc4;padding-left:14px;margin:14px 0}a{color:#274bc4}@media(max-width:600px){main{padding:20px 16px}section{padding:16px}ul{grid-template-columns:1fr;gap:16px}}
</style></head><body><main><p class="mode">Actual MCP SDK child-process stdio · No model call</p><h1>Connect retrieval tools through MCP</h1><section><h2>Real SDK lifecycle</h2><p>ClientSession initialize → tools/list → tools/call</p><p>Negotiated compatibility protocol: '''+escape(initialized['protocolVersion'])+'</p><p>Discovered tools: '+escape(tools)+'</p><p>'+str(methods.count('tools/call'))+' calls in the recorded live session · '+str(len(record['protocol_transcript']))+' observed protocol messages</p><p class="note">Server stdout carries protocol only. Lifecycle logs go to stderr. The registry closes after the session.</p></section><section><h2>Issued search handle read</h2><p><strong>'+escape(read['source_id'])+' · version '+escape(read['version'])+'</strong> · line '+str(read['start_line'])+'</p><blockquote>'+escape(read['text'])+'</blockquote><p class="note">Structured/text output, source hashes, bytes and original handle binding were validated. This does not establish answer correctness.</p></section><section><h2>Actual calls and error semantics</h2><ul>'+''.join(rows)+'</ul></section><section><h2>Process and source boundaries</h2><p>Fresh child reading the old handle: isError '+str(record['fresh_process_read']['isError']).lower()+'.</p><p>Changed pinned snapshot: '+escape(record['changed_snapshot_startup']['status'])+'. No initialization response.</p><p>Unknown tool: '+escape(record['unknown_tool']['kind'])+' with isError true in this SDK run.</p><p class="note">No HTTP server, authentication or cross-service authorization is demonstrated. Receipt continuity is not an access-control system.</p></section><p class="note">Full schemas, actual protocol messages, source receipts and diagnostics: <a href="/examples/connect-retrieval-tools-through-mcp/runs/2026-10-23-mcp/result.json">raw run record</a>. '+escape(record['limit'])+'</p></main></body></html>'


if __name__=='__main__':
    root=Path(__file__).parent;record=json.loads((root/'runs/2026-10-23-mcp/result.json').read_text())
    target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(render(record),encoding='utf-8');print(target)
