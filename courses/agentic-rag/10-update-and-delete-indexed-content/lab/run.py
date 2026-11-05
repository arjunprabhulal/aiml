"""Execute actual FTS5 queries across transactional updates and deletions."""
import argparse
import json
from pathlib import Path
import sqlite3
from index import connect, delete_source, replace_source, search, state


def run(path):
    if path.exists():raise ValueError('use a new database path for the recorded sequence')
    root=Path(__file__).parent/'fixtures'
    initial=json.loads((root/'snapshot.json').read_text());updated=json.loads((root/'updated-snapshot.json').read_text())
    before={d['source_id']:d for d in initial['documents']}
    changed=next(d for d in updated['documents'] if d['document_revision']!=before[d['source_id']]['document_revision'])
    db=connect(path);steps=[]
    try:
        for source in initial['documents']:replace_source(db,source)
        steps.append({'operation':'load-original-snapshot','state':state(db),'query':'saving','matches':search(db,'saving')})
        old_ids=[c['chunk_id'] for c in before[changed['source_id']]['chunks']]
        try:
            replace_source(db,changed,interrupt=True)
        except InterruptedError as error:
            steps.append({'operation':'interrupt-replacement-before-commit','status':'rolled-back','error':str(error),'state':state(db),'query':'saving','matches':search(db,'saving')})
        replace_source(db,changed)
        steps.append({'operation':'replace-changed-source','source_id':changed['source_id'],'retired_chunk_ids':old_ids,'state':state(db),'query':'saving','matches':search(db,'saving')})
        try:
            delete_source(db,changed['source_id'],interrupt=True)
        except InterruptedError as error:
            steps.append({'operation':'interrupt-deletion-before-commit','status':'rolled-back','error':str(error),'state':state(db),'query':'saving','matches':search(db,'saving')})
        outcome=delete_source(db,changed['source_id'])
        steps.append({'operation':'delete-source','outcome':outcome,'state':state(db),'query':'saving','matches':search(db,'saving')})
        steps.append({'operation':'repeat-delete','outcome':delete_source(db,changed['source_id']),'state':state(db),'query':'saving','matches':search(db,'saving')})
    finally:db.close()
    return {'execution_mode':'offline-sqlite-source-maintenance','model_called':False,'sqlite_version':sqlite3.sqlite_version,'initial_snapshot_id':initial['snapshot_id'],'updated_snapshot_id':updated['snapshot_id'],'steps':steps}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database',type=Path,required=True)
    print(json.dumps(run(parser.parse_args().database),indent=2))
