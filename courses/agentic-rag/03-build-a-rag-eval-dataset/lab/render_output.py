"""Execute dataset checks, then display actual declared targets and failures."""
from html import escape
from pathlib import Path
import argparse,json,subprocess,sys
ROOT=Path(__file__).parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--html",type=Path,default=Path("/tmp/rag-dataset-runtime/report.html"));args=parser.parse_args()
    subprocess.run([sys.executable,"build_dataset.py"],cwd=ROOT,check=True)
    record=json.loads((ROOT/"runs/2026-10-22-dataset/validation.json").read_text());cards=[]
    for q in record["questions"]:
        targets=", ".join(t["source_id"]+" / "+t["source_version"]for t in q["targets"])or"No relevant passage in this corpus"
        cards.append(f'<article><h2>{escape(q["question"])}</h2><p>{escape(q["split"])} · {escape(q["class"])} · Python {escape(q["python_version"])}</p><p><strong>Expected handling:</strong> {escape(q["status"])}</p><p><strong>Labelled targets:</strong> {escape(targets)}</p></article>')
    counts=record["counts"];summary=f'{counts["cases"]} authored questions · {counts["sources"]} source summaries · {counts["by_split"]["development"]} development / {counts["by_split"]["held_out"]} held out'
    failures=''.join(f'<p>{escape(f["case"])}: <strong>{escape(f["error_type"])}</strong></p>'for f in record['controlled_failures'])
    html='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Build a RAG Eval Dataset</title><style>body{margin:0;background:#fff;color:#192136;font:18px/1.5 Arial,sans-serif}main{box-sizing:border-box;width:760px;max-width:calc(100% - 32px);padding:24px;margin:20px auto;border:1px solid #dfe4ed;border-radius:8px}h1{font-size:30px;line-height:1.2;margin:8px 0 20px}h2{font-size:21px;line-height:1.35;margin:0 0 10px}p{margin:8px 0}article{border:1px solid #dfe4ed;padding:16px;border-radius:6px;margin:16px 0}footer,.mode{font-size:17px;color:#596375}strong{overflow-wrap:anywhere}@media(max-width:600px){body{font-size:17px}main{padding:16px}h1{font-size:25px}h2{font-size:20px}footer,.mode{font-size:17px}}</style><main><p class="mode">Executed local dataset validation · no model calls</p><h1>Build a RAG Eval Dataset</h1><p><strong>Questions, Relevance Labels, and Answerability Checks</strong></p>'f'<p>{escape(summary)}</p><p>These are authored expected labels, not generated answers or measured model accuracy. Python 3.13 facts are documented-only.</p>'+"".join(cards)+f'<article><h2>Executed invalid-data cases</h2>{failures}</article><footer>IDs, versions, hashes and frozen-split relationships passed their checks. A valid target can still be an incorrect human relevance label. Raw report: runs/2026-10-22-dataset/validation.json</footer></main></html>'
    args.html.parent.mkdir(parents=True,exist_ok=True);args.html.write_text(html);print(args.html)

if __name__=="__main__":main()
