"""A local Prefect pipeline for the shared user-return application."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import foundations as f
import workflow as w
import tracking

# Set before importing Prefect. No Cloud URL, credentials or analytics.
os.environ['PREFECT_SERVER_ANALYTICS_ENABLED']='false'
os.environ.pop('PREFECT_API_URL',None)
os.environ.pop('PREFECT_API_KEY',None)
os.environ['PREFECT_HOME']=str(Path(os.environ.get('RETURN_PREFECT_HOME',str(Path(tempfile.gettempdir())/'user-return-prefect'))).resolve())
Path(os.environ['PREFECT_HOME']).mkdir(parents=True,exist_ok=True)
os.environ['MLFLOW_DISABLE_TELEMETRY']='true'
from prefect import flow, task
from prefect.cache_policies import NO_CACHE


def pipeline_identity(source):
    return f.digest({'contract':f.contract(source),'trainer':w.sha(w.HERE/'tracking.py'),
                     'pipeline':w.sha(Path(__file__)),'dependencies':w.sha(w.HERE/'requirements-platform.txt')})


@task(cache_policy=NO_CACHE,persist_result=False)
def validate_events(source, folder):
    report=f.validate_source(source,Path(folder)/'ingestion')
    w.save(Path(folder)/'validation.json',report)
    if report['status']!='ready':raise ValueError('invalid batch blocks training')
    # The trainer must use the accepted bytes, not the original unvalidated list.
    fixture=w.strict_json(source)
    accepted=Path(folder)/'ingestion'/report['training_file']
    fixture['events']=[json.loads(line) for line in accepted.read_text().splitlines()]
    path=Path(folder)/'accepted-scenario.json';w.save(path,fixture)
    return str(path)


@task(cache_policy=NO_CACHE,persist_result=False)
def materialize_cohort(source, folder):
    folder=Path(folder);database=folder/'features.sqlite'
    report=f.publish_history(source,database)
    fixture=w.strict_json(source);store=f.ReturnHistory(database)
    try:joined=store.join(fixture['observations'],'user_events_1d@v1')
    finally:store.close()
    by_id={row['id']:row['feature']['value'] for row in joined}
    cohort=w.prepare(source)
    for row in cohort['rows']:row['feature_count']=by_id[row['id']]
    if cohort!=w.prepare(source):raise ValueError('historical and direct feature values differ')
    target=folder/'cohort.json';w.save(target,cohort);w.save(folder/'history.json',report)
    return str(target)


def retry_transient(task, task_run, state):
    try:state.result()
    except FileExistsError:return False
    except OSError:return True
    except Exception:return False
    return False


@task(retries=1,retry_delay_seconds=0,retry_condition_fn=retry_transient,cache_policy=NO_CACHE,persist_result=False)
def write_receipt(folder, summary, inject_once=False):
    folder=Path(folder);attempts=folder/'receipt-attempts'
    attempt=int(attempts.read_text())+1 if attempts.exists() else 1
    attempts.write_text(str(attempt))
    if inject_once and attempt==1:raise OSError('controlled transient receipt-write failure')
    # Exclusive creation prevents a retry from overwriting an earlier receipt.
    w.save(folder/'complete.json',dict(summary,receipt_attempts=attempt))
    return attempt


@flow(name='user-return-training',persist_result=False,log_prints=False)
def train_flow(source, folder, inject_once=False):
    accepted=validate_events(str(source),str(folder))
    cohort=materialize_cohort(accepted,str(folder))
    summary=tracking.execute(accepted,Path(folder)/'tracker',prepared_cohort=cohort)
    summary['workspace']=str(Path(folder).resolve())
    summary['pipeline_id']=pipeline_identity(source)
    summary['accepted_source_sha256']=w.sha(accepted)
    summary['prepared_cohort_sha256']=w.sha(cohort)
    summary['execution']='actual local Prefect tasks, SQLite history and CPU fitting'
    summary['receipt_attempts']=write_receipt(str(folder),summary,inject_once)
    return summary


def run(source, workspace, inject_once=False):
    source=Path(source).resolve();workspace=Path(workspace).resolve();workspace.mkdir(parents=True,exist_ok=True)
    identity=pipeline_identity(source);folder=workspace/identity
    folder.mkdir(exist_ok=True)
    # A single-process lock makes two simultaneous invocations fail closed.
    lock=folder/'running.lock'
    try:handle=lock.open('x')
    except FileExistsError:raise ValueError('pipeline already running; inspect owner before recovery')
    with handle:
        try:
            receipt=folder/'complete.json'
            if receipt.exists():
                result=w.strict_json(receipt)
                model=folder/'tracker/runs'/result['run_id']/'workspace/outputs/candidate.json'
                cohort=folder/'cohort.json'
                snapshot=folder/'tracker/runs'/result['run_id']/'workspace'
                manifest=w.strict_json(snapshot/'contract.json')
                if w.sha(snapshot/'scenario.json')!=manifest['dataset_sha256']:
                    raise ValueError('saved source dataset changed')
                for name,digest in manifest['implementation'].items():
                    if w.sha(snapshot/name)!=digest:raise ValueError('saved implementation changed')
                checked=w.evaluate(cohort,model)
                if (result['pipeline_id']!=identity or w.sha(model)!=result['model_sha256']
                    or w.sha(cohort)!=result['prepared_cohort_sha256']
                    or checked['accuracy']!=result['validation_accuracy']):
                    raise ValueError('completed result identity or artifact changed')
                return dict(result,reused=True)
            # A failed attempt is kept; recovery uses an explicit fresh workspace.
            if any(p.name!='running.lock' for p in folder.iterdir()):
                raise ValueError('incomplete attempt retained; choose a fresh workspace')
            result=train_flow(source,folder,inject_once)
            return dict(result,reused=False,workspace=str(folder))
        finally:lock.unlink()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=w.HERE/'scenario.json');p.add_argument('--workspace',type=Path,default=Path('work/pipeline'));p.add_argument('--inject-receipt-failure',action='store_true');p.add_argument('--out',type=Path)
    a=p.parse_args()
    try:
        result=run(a.source,a.workspace,a.inject_receipt_failure)
        if a.out:w.save(a.out,result)
        print(json.dumps(result,indent=2))
    except (ValueError,OSError) as e:p.exit(2,str(e)+'\n')


if __name__=='__main__':main()
