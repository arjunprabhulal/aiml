"""Execute a real interruption, close/reopen, resume and retry using SQLite."""
import argparse
import json
from pathlib import Path
import sqlite3
from ingest import connect, ingest, state


def run(path):
    if path.exists():
        raise ValueError('use a new database path so the interruption trace is reproducible')
    snapshot=json.loads((Path(__file__).parent/'fixtures/snapshot.json').read_text())
    steps=[];db=connect(path)
    try:
        try:
            ingest(db,snapshot,'python-docs-v1',snapshot['documents'][1]['source_id'])
        except InterruptedError as error:
            steps.append({'operation':'interrupt-before-second-source-commit','status':'interrupted','error':str(error),'state':state(db)})
    finally:db.close()
    db=connect(path)
    try:
        steps.append({'operation':'close-reopen-and-resume','status':'completed','actions':ingest(db,snapshot,'python-docs-v1'),'state':state(db)})
        steps.append({'operation':'retry-completed-job','status':'completed','actions':ingest(db,snapshot,'python-docs-v1'),'state':state(db)})
    finally:db.close()
    return {'execution_mode':'offline-sqlite-source-maintenance','model_called':False,'sqlite_version':sqlite3.sqlite_version,'snapshot_id':snapshot['snapshot_id'],'steps':steps}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database',type=Path,required=True)
    print(json.dumps(run(parser.parse_args().database),indent=2))
