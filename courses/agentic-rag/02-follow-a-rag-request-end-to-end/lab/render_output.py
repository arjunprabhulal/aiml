"""Run the local replay pipeline and render its actual transition record."""
from html import escape
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--html",type=Path,default=Path("/tmp/rag-request-runtime/report.html"));args=parser.parse_args()
    subprocess.run([sys.executable,"trace_run.py"],cwd=ROOT,env={**os.environ,"PYTHONPATH":str(ROOT/"src")},check=True)
    data=json.loads((ROOT/"runs/2026-10-22-request/request-trace.json").read_text())
    cards=[]
    for request in data["requests"]:
        result=request["result"];ranked=request["events"][1]["candidates"]
        rows="".join(f'<li><strong>{c["rank"]}. {escape(c["source_id"])}</strong> · similarity {c["score"]:.4f}</li>'for c in ranked)
        steps="".join(f'<li>{escape(event["kind"])}</li>'for event in request["events"])
        sources=", ".join(result["source_ids"]) or "(none)"
        cards.append(f'<article><h2>{escape(result["question"])}</h2><p><strong>{escape(result["status"])}</strong> · source IDs: {escape(sources)}</p><ul>{rows}</ul><p>{escape(result["answer"])}</p><details open><summary>Actual local event order</summary><ol>{steps}</ol></details></article>')
    limits='<article><h2>Executed refusal paths</h2><p>Empty maintained index: model_skipped, no adapter call.</p>'+''.join(f'<p>{escape(f["case"])}: <strong>{escape(f["error_type"])}</strong></p>'for f in data['failures'])+'</article>'
    html='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Build a RAG Pipeline</title><style>body{margin:0;background:#fff;color:#192136;font:18px/1.5 Arial,sans-serif}main{box-sizing:border-box;width:760px;max-width:calc(100% - 32px);margin:20px auto;padding:24px;border:1px solid #dfe4ed;border-radius:10px}h1{font-size:30px;line-height:1.2;margin:8px 0 20px}h2{font-size:22px;line-height:1.35;margin:0 0 12px}p{margin:10px 0}article{padding:18px;border:1px solid #dfe4ed;border-radius:6px;margin:18px 0}ul,ol{padding-left:23px}li{margin:3px 0}summary{font-weight:700}footer,.mode{font-size:17px;color:#596375}strong{overflow-wrap:anywhere}@media(max-width:600px){body{font-size:17px}main{padding:16px}h1{font-size:25px}h2{font-size:20px}article{padding:14px}footer,.mode{font-size:17px}}</style><main><p class="mode">Executed local retrieval + exact-request replay</p><h1>Build a RAG Pipeline</h1><p><strong>Retrieval, Context Assembly, and Answer Generation</strong></p><p>Current local ranking, context and checks. Generated answers below are saved Gemma output from the earlier run; no new model inference.</p>'+"".join(cards)+limits+'<footer>Sequence numbers are local operation order, not model latency or distributed spans. Similarity does not mean answer correctness. Raw record: runs/2026-10-22-request/request-trace.json</footer></main></html>'
    args.html.parent.mkdir(parents=True,exist_ok=True);args.html.write_text(html);print(args.html)

if __name__=="__main__":main()
