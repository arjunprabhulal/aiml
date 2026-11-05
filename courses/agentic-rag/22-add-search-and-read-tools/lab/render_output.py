"""Render actual native search metadata and exact local read results."""
import argparse
from html import escape
import json
from pathlib import Path

def render(result):
    reads=[]
    for row in result['reads']:
        reads.append('<article><h2>Read '+escape(row['source_id'])+'</h2><p>Python '+escape(row['version'])+' · lines '+str(row['start_line'])+'–'+str(row['end_line'])+' · '+str(row['byte_count'])+' UTF-8 passage bytes</p><blockquote>'+escape(row['text'])+'</blockquote><p>Bound source URL: '+escape(row['url'])+'</p></article>')
    return page('Documentation search and read','Actual local SQLite FTS5 + exact passage resolution · No model execution', '<article><h2>Search '+escape(result['search']['query'])+'</h2><p>Requested Python '+escape(result['search']['version'])+' · '+str(len(result['search']['results']))+' metadata-only handle(s)</p><p>Search returns IDs, revisions, spans and hashes. Passage text arrives only from read.</p></article>'+''.join(reads)+'<article><h2>Recorded failure boundaries</h2><p>Changed handle: <strong>'+escape(result['changed_handle_refusal'])+'</strong></p><p>No-hit count '+str(len(result['no_match']['results']))+' · Ineligible-version count '+str(len(result['empty_eligible_version']['results']))+'</p></article>')

def page(title,subtitle,body):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>'+escape(title)+'</title><style>*{box-sizing:border-box}body{margin:0;font:17px/1.5 system-ui,sans-serif;background:#fff;color:#192136}main{max-width:1100px;margin:auto;padding:32px 24px}h1{font-size:32px;margin:0 0 12px}h2{font-size:23px}p{overflow-wrap:anywhere}.mode{color:#596375}article{border:1.5px solid #192136;border-radius:8px;background:#dcfce7;padding:18px;margin:16px 0}blockquote{border-left:3px solid #274bc4;padding-left:14px;margin:16px 0;overflow-wrap:anywhere}@media(max-width:700px){main{padding:24px 16px}h1{font-size:27px}}</style><main><h1>'+escape(title)+'</h1><p class="mode">'+escape(subtitle)+'</p>'+body+'</main></html>'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(render(json.loads(args.input.read_text(encoding='utf-8'))),encoding='utf-8')
