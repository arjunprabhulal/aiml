"""Add, replace, reopen and delete chunks through PGVectorStore."""
from datetime import datetime, timezone
import json
from pathlib import Path
from langchain_core.documents import Document
from library import documents, RecordedEmbeddings, vector_store
from pg_cluster import Cluster
ROOT=Path(__file__).parent

def main():
    saved=json.loads((ROOT/'vectors.json').read_text()); chunks=documents()
    question='How do I roll back a service?'
    with Cluster() as pg:
        with vector_store(pg.url,RecordedEmbeddings(saved)) as store:
            store.add_documents(chunks,ids=[d.id for d in chunks])
            before=store.similarity_search(question,k=3,filter={'team':'platform'})
            # Stable IDs make a retry replace those rows rather than duplicate them.
            store.add_documents(chunks,ids=[d.id for d in chunks])
        with vector_store(pg.url,RecordedEmbeddings(saved),initialize=False) as store:
            reopened=store.similarity_search(question,k=100)
            deleted=[d.id for d in chunks if d.metadata['source']=='platform/deploy']
            store.delete(ids=deleted)
            after=store.similarity_search(question,k=100)
    output={'recorded_at':datetime.now(timezone.utc).isoformat(),'initial_chunks':len(chunks),
        'after_retry_and_reopen':len(reopened),'deleted_ids':deleted,'remaining_chunks':len(after),
        'before_top_sources':[d.metadata['source'] for d in before],
        'deleted_ids_still_present':sorted(set(deleted)&{d.id for d in after})}
    (ROOT/'library-lifecycle.json').write_text(json.dumps(output,indent=2)+'\n'); print(json.dumps(output,indent=2))
if __name__=='__main__': main()
