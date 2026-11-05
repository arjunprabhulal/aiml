"""Render saved live API results, explicitly labelled; makes no model calls."""
import argparse
from html import escape
import json
from pathlib import Path

ROOT = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', type=Path, required=True)
    args = parser.parse_args()
    report = json.loads((ROOT/'runs/gemini/result.json').read_text())
    trial = next(t for t in report['trials'] if t['id'] == 'serialize-and-save-agent-1')
    rows = ''.join('<tr>' + ''.join('<td>'+escape(str(v))+'</td>' for v in
                   (t['case_id'], t['mode'], t['repeat'], t['checks']['outcome'], t['result']['reason'])) + '</tr>' for t in report['trials'])
    steps = ''.join('<li><strong>'+escape(d['action'])+'</strong> '+escape(d['query'] or d['source_id'])+'</li>' for d in trial['result']['decisions'])
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Model-driven RAG: recorded output</title><style>
body{margin:0;background:white;color:#192136;font:17px/1.5 Arial,sans-serif}main{max-width:1040px;margin:auto;padding:28px}h1{font-size:30px;line-height:1.2}h2{font-size:21px}p{max-width:72ch}.mode{color:#596375}section{padding:16px;border:1px solid #dfe4ed;margin:20px 0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:15px}td,th{padding:8px;text-align:left;border-bottom:1px solid #dfe4ed;white-space:nowrap}li{padding:4px 0;overflow-wrap:anywhere}code{font-size:15px} @media(max-width:600px){main{padding:16px}h1{font-size:26px}}
</style><main><p class="mode">Saved live Gemini API run · report inspection · no new inference</p><h1>Model-driven RAG: evidence guides another search</h1>'''
    html += f'<p>{escape(report["model"])} · LOW thinking · {report["actual_api_requests"]} actual API requests · {len(report["trials"])} retained trials</p>'
    html += '<section><h2>JSON serialization → file-writing evidence</h2><ol>'+steps+'</ol><p>'+escape(trial['result']['answer'])+'</p></section>'
    html += '<section><h2>Same tasks, different control flow</h2><div class="scroll"><table><thead><tr><th>Task</th><th>Path</th><th>Repeat</th><th>Fixture check</th><th>Stop reason</th></tr></thead><tbody>'+rows+'</tbody></table></div></section>'
    html += '<p>Both paths passed the same number of authored fixtures. Both made unsupported backup claims. Source-ID and exact-quote checks do not prove the answer follows from the evidence.</p><p class="mode">Raw evidence: runs/gemini/result.json and per-trial request/reply records. Tiny authored corpus; no general quality or billing-cost estimate.</p></main></html>'
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(html)
    print(args.html)


if __name__ == '__main__': main()
