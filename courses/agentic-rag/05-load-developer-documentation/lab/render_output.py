"""Render an executed ingestion result as an HTML report; no model calls."""
import argparse
from html import escape
import json
from pathlib import Path

def render(result: dict) -> str:
    documents = result['documents']
    failures = result.get('failures', [])
    status = result.get('status', 'complete')
    cards = []
    for document in documents:
        metadata = ' · '.join(str(document.get(key, '')) for key in ('path', 'version', 'fact_status'))
        cards.append('<article><h2>' + escape(document['source_id']) + '</h2><p class="meta">' + escape(metadata) + '</p><p>' + escape(document['text']) + '</p><p class="meta">SHA-256 <code>' + escape(document['sha256']) + '</code></p><a href="' + escape(document['url'], quote=True) + '">Python documentation reference</a></article>')
    for failure in failures:
        cards.append('<article class="rejected"><h2>' + escape(failure['source_id']) + '</h2><p>' + escape(failure['path']) + '</p><p>Rejected: <code>' + escape(failure['error']) + '</code></p></article>')
    heading = 'Ingestion failure handling' if failures else 'Loaded developer documentation'
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>''' + heading + '''</title><style>
*{box-sizing:border-box}body{margin:0;background:#fff;color:#192136;font:17px/1.55 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:40px 24px}h1{font-size:clamp(25px,4vw,36px);line-height:1.2;margin:0 0 14px}h2{font-size:20px;margin:0 0 8px}.mode{color:#596375}.summary{background:#dbeafe;border:1px solid #192136;padding:16px;margin:24px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}article{border:1.5px solid #192136;border-radius:8px;padding:20px;background:#dcfce7}.rejected{background:#ffe4e6;border-style:dashed}.meta{font-size:14px;color:#596375}code{overflow-wrap:anywhere}a{color:#274bc4;overflow-wrap:anywhere}p{margin:10px 0}@media(max-width:650px){main{padding:24px 16px}.grid{grid-template-columns:1fr}article{padding:16px}}</style><main><h1>''' + heading + '</h1><p class="mode">Actual executed local file ingestion · Offline · No model inference</p><p>Four pinned original Python API summaries from the RAG baseline. Documentation versions remain attached to each source.</p><div class="summary">Batch status: <strong>' + escape(status) + '</strong> · Loaded: <strong>' + str(len(documents)) + '</strong> · Rejected: <strong>' + str(len(failures)) + '</strong></div><div class="grid">' + ''.join(cards) + '</div></main></html>'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.input.read_text(encoding='utf-8'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(result), encoding='utf-8')

if __name__ == '__main__': main()
