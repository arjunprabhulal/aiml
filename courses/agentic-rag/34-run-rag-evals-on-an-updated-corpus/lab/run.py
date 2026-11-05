"""Execute actual fixed-development native rankings on both pinned snapshots."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import socket
import sqlite3
import subprocess
import sys
from evaluation import CONFIG,load_inputs,requests_from_cases,run_rankings,compare_runs
from evaluation_bindings import bind_targets
ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve();out.parent.mkdir(parents=True,exist_ok=True)
    attempts=[]
    def deny(*args,**kwargs):attempts.append('connect');raise RuntimeError('network_disabled')
    connect,connect_ex=socket.socket.connect,socket.socket.connect_ex;socket.socket.connect=deny;socket.socket.connect_ex=deny
    try:
        before,after,cases,annotations=load_inputs();requests=requests_from_cases(cases)
        previous=run_rankings(before,requests);current=run_rankings(after,requests)
        try:bind_targets(after,cases)
        except ValueError as error:refusal={'status':'refused','code':str(error)}
        else:raise AssertionError('stale labels must fail')
        comparison=compare_runs(before,after,previous,current,cases,annotations)
    finally:socket.socket.connect=connect;socket.socket.connect_ex=connect_ex
    result={'schema_version':1,'mode':'actual-offline-sqlite-fixed-development-evaluation','model_called':False,'synthetic_update':{'description':'Retain original path-write summary; append explicit synthetic non-factual length padding; delete json-text. Not an official documentation update.','before_snapshot_id':before['snapshot_id'],'after_snapshot_id':after['snapshot_id']},'config':CONFIG,'stale_binding_refusal':refusal,'baseline_run':previous,'updated_run':current,'comparison':comparison,'network_connection_attempts':attempts}
    out.write_text(json.dumps(result,indent=2)+'\n')
    lines=['Fixed development corpus-update evaluation (SQLite FTS5; no model)',f"Stale labels: {refusal['status']} ({refusal['code']})"]
    for row in comparison['per_case']:
        if row['comparison']=='paired-supported':
            old=row['before']['metrics']['1'];new=row['after']['metrics']['1'];lines.append(f"{row['case_id']}: target ranks {old['target_ranks']} -> {new['target_ranks']}; recall@1 {old['recall_at_k']} -> {new['recall_at_k']}; target denominator={new['target_count']}")
        else:lines.append(f"{row['case_id']}: {row['comparison']}; metrics null")
    for k,aggregate in comparison['paired_aggregate'].items():lines.append(f"Paired recall@{k}: {aggregate['before_mean_recall']} -> {aggregate['after_mean_recall']}; supported case denominator={aggregate['paired_supported_denominator']}")
    lines.append('Development-only observations; no quality gain or held-out estimate claimed.')
    stdout='\n'.join(lines)+'\n';print(stdout,end='');(out.parent/'stdout.txt').write_text(stdout);(out.parent/'stderr.txt').write_text('')
    tests=subprocess.run([sys.executable,'-m','unittest','discover','-v'],cwd=ROOT,text=True,capture_output=True);(out.parent/'tests.txt').write_text(tests.stdout+tests.stderr)
    sources={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(ROOT.rglob('*')) if f.is_file() and 'runs' not in f.relative_to(ROOT).parts and '__pycache__' not in f.parts}
    execution={'command':[sys.executable,*sys.argv],'working_directory':str(Path.cwd()),'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'dependencies':'stdlib; SQLite FTS5 required','test_command':[sys.executable,'-m','unittest','discover','-v'],'test_exit_code':tests.returncode,'source_sha256':sources,'result_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'network':'connect/connect_ex refused during rankings; no attempted connections','model_called':False}
    (out.parent/'execution.json').write_text(json.dumps(execution,indent=2)+'\n')
    if tests.returncode:raise SystemExit(tests.returncode)
if __name__=='__main__':main()
