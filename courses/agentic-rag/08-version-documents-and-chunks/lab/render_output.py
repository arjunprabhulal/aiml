"""Display saved versioning results; this does not rerun ingestion."""
import argparse
from html import escape
import json
from pathlib import Path

def render(result):
    cards=[]
    for name,snapshot in result['snapshots'].items():
        paragraphs=[]
        for document in snapshot['documents']:
            paragraphs.append('<h3>'+escape(document['source_id'])+' · API '+escape(document['version'])+'</h3><p>Byte revision <code>'+escape(document['sha256'])+'</code></p><p>Document revision <code>'+escape(document['document_revision'])+'</code></p><p>'+str(len(document['chunks']))+' paragraph chunks</p>')
        change=result['comparisons'].get(name)
        summary='Baseline: four source summaries.' if change is None else '; '.join(c['source_id']+': raw bytes '+str(c['raw_bytes_changed']).lower()+', metadata '+str(c['metadata_changed']).lower()+', chunk IDs '+str(c['chunk_ids_changed']).lower() for c in change['changed'])
        cards.append('<article><h2>'+escape(name)+'</h2><p>'+escape(summary)+'</p><p>Snapshot <code>'+escape(snapshot['snapshot_id'])+'</code></p>'+''.join(paragraphs)+'</article>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Document and chunk versions</title><style>*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,sans-serif;color:#192136;background:#fff}main{max-width:1100px;margin:auto;padding:30px 24px}h1{font-size:32px;margin:0 0 12px}h2{font-size:23px}h3{font-size:18px;margin-bottom:6px}p{margin:7px 0}.mode{color:#596375}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}article{background:#fef3c7;border:1.5px solid #192136;border-radius:8px;padding:18px}code{font-size:16px;overflow-wrap:anywhere}@media(max-width:800px){.grid{grid-template-columns:1fr}main{padding:24px 16px}h1{font-size:27px}}</style><main><h1>Document and chunk versions</h1><p class="mode">Actual executed offline file processing · No model inference</p><p>Deliberate local fixture changes. No upstream documentation refresh is claimed. Each source keeps its logical ID and API version while byte, metadata and chunk identities track changes.</p><div class="grid">'''+''.join(cards)+'</div></main></html>'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(render(json.loads(args.input.read_text(encoding='utf-8'))),encoding='utf-8')

if __name__=='__main__':main()
