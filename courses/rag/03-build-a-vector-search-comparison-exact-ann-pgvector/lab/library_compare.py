"""Observe exact/HNSW/IVFFlat on this small docs set, not a speed benchmark."""
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
import psycopg
from langchain_postgres.v2.indexes import HNSWIndex, IVFFlatIndex
from library import documents, RecordedEmbeddings, vector_store
from pg_cluster import Cluster
ROOT=Path(__file__).parent

def compare():
    saved=json.loads((ROOT/'vectors.json').read_text())
    questions=json.loads((ROOT/'questions.json').read_text())
    chunks=documents()
    rows=[]
    with Cluster() as pg:
        with vector_store(pg.url,RecordedEmbeddings(saved)) as store:
            store.add_documents(chunks,ids=[d.id for d in chunks])
        url=pg.url.replace('postgresql+psycopg://','postgresql://')
        with psycopg.connect(url,autocommit=True) as connection:
            # A new connection pool below will inherit this lab-only setting.
            connection.execute('ALTER ROLE rag SET enable_seqscan = off')
        for name,index in [('exact',None),('hnsw',HNSWIndex(m=8,ef_construction=32)),('ivfflat',IVFFlatIndex(lists=4))]:
            with vector_store(pg.url,RecordedEmbeddings(saved),initialize=False) as store:
                if index is not None: store.apply_vector_index(index,name='docs_ann')
                cases=[]
                for q in questions:
                    started=perf_counter()
                    hits=store.similarity_search(q['question'],k=3,filter={'team':q['team']})
                    cases.append({'question':q['question'],'ids':[d.id for d in hits],
                                  'elapsed_ms':(perf_counter()-started)*1000})
                with psycopg.connect(url) as connection:
                    vector=str(saved['queries'][questions[0]['question']])
                    plan=connection.execute('EXPLAIN (FORMAT JSON) SELECT langchain_id FROM docs WHERE team=%s ORDER BY embedding <=> %s::vector LIMIT 3',('platform',vector)).fetchone()[0]
                rows.append({'mode':name,'index_parameters':None if index is None else {k:v for k,v in vars(index).items() if k in ['m','ef_construction','lists']},'plan':plan,'queries':cases})
                if index is not None: store.drop_vector_index('docs_ann')
        # PostgreSQL normally prefers a sequential scan for this tiny corpus.
        with psycopg.connect(url) as connection:
            connection.execute('SET enable_seqscan=on')
            default_plan=connection.execute('EXPLAIN (FORMAT JSON) SELECT langchain_id FROM docs ORDER BY embedding <=> %s::vector LIMIT 3',(str(saved['queries'][questions[0]['question']]),)).fetchone()[0]
    exact={q['question']:set(q['ids']) for q in rows[0]['queries']}
    for row in rows:
        for q in row['queries']: q['recall_at_3']=len(set(q['ids'])&exact[q['question']])/len(exact[q['question']])
    return {'recorded_at':datetime.now(timezone.utc).isoformat(),'documents':len(chunks),
            'query_setting':'enable_seqscan=off for the index exercise only',
            'default_plan':default_plan,'runs_per_query_and_mode':1,'modes':rows}
if __name__=='__main__':
    output=compare(); (ROOT/'library-comparison.json').write_text(json.dumps(output,indent=2)+'\n'); print(json.dumps(output,indent=2))
