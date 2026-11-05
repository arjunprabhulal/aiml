"""Run one fresh, cited answer over the bundled internal developer docs."""
import json
from pathlib import Path
import sys
from ollama import Client
from library import DocsEmbeddings, MODEL, answer_question, check_identity, documents, identity, vector_store
from pg_cluster import Cluster
ROOT=Path(__file__).parent

def main(question:str):
    chunks=documents()
    digest=next(m.digest for m in Client().list().models if m.model==MODEL)
    saved=json.loads((ROOT/'vectors.json').read_text())
    check_identity(saved['identity'],identity(chunks,digest))
    embeddings=DocsEmbeddings(model=MODEL)
    with Cluster() as pg:
        with vector_store(pg.url,embeddings) as store:
            store.add_documents(chunks,ids=[d.id for d in chunks])
            selected=store.similarity_search(question,k=3,filter={'team':'platform'})
            result=answer_question(question,selected)
            if result['citation_error']:
                raise ValueError(result['citation_error'])
    print(json.dumps(result,indent=2,default=str))
if __name__=='__main__': main(sys.argv[1] if len(sys.argv)>1 else 'How do I roll back a service?')
