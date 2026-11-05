"""Record actual local SQLite ranking and tokenizer observations."""
import argparse
import json
from pathlib import Path
import sqlite3
from bm25 import LexicalIndex

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    snapshot=json.loads((Path(__file__).parent/'fixtures/snapshot.json').read_text(encoding='utf-8'))
    index=LexicalIndex(snapshot)
    try:
        queries=[index.search(query) for query in ['text','newline','overwritten','xyznotindexed','']]
        rejected=[]
        for query in ['text OR newline','text*','"','x; DROP TABLE passages;']:
            try:index.search(query)
            except ValueError as error:rejected.append({'query':query,'error':str(error)})
        result={'execution_mode':'offline-native-sqlite-fts5','sqlite_version':sqlite3.sqlite_version,'snapshot_id':snapshot['snapshot_id'],'tokenizer':'unicode61','bm25':{'k1':1.2,'b':0.75,'ordering':'native_score ASC, chunk_id ASC','scope':'single term, one indexed text column, no column weights'},'indexed_terms':index.indexed_terms(),'queries':queries,'rejected_queries':rejected}
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'execution_mode':result['execution_mode'],'queries':[{'query':q['query'],'status':q['status'],'order':[r['source_id'] for r in q['results']],'native_scores':[r['native_score'] for r in q['results']]} for q in queries],'rejected':len(rejected)},sort_keys=True))
    finally:index.close()

if __name__=='__main__':main()
