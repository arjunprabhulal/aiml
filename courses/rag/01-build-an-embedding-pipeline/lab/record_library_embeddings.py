"""Record current local embeddings and a PostgreSQL search, without generation."""
import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from ollama import Client
from library import DocsEmbeddings, MODEL, documents, identity, vector_store
from pg_cluster import Cluster

ROOT = Path(__file__).parent

def main():
    chunks = documents()
    questions = json.loads((ROOT / 'questions.json').read_text())
    models = Client().list().models
    digest = next(m.digest for m in models if m.model == MODEL)
    embeddings = DocsEmbeddings(model=MODEL)
    started = perf_counter()
    vectors = embeddings.embed_documents([d.page_content for d in chunks])
    queries = {q['question']: embeddings.embed_query(q['question']) for q in questions}
    elapsed = perf_counter() - started
    manifest = identity(chunks, digest)
    record = {'identity': manifest, 'documents': dict(zip([d.page_content for d in chunks], vectors)),
              'queries': queries}
    (ROOT / 'vectors.json').write_text(json.dumps(record, indent=2) + '\n')
    # Use the saved vectors to separate model work from PostgreSQL work.
    from library import RecordedEmbeddings
    rows = []
    with Cluster() as pg:
        with vector_store(pg.url, RecordedEmbeddings(record)) as store:
            store.add_documents(chunks, ids=[d.id for d in chunks])
            for q in questions:
                hits = store.similarity_search_with_score(q['question'], k=3, filter={'team': q['team']})
                rows.append({**q, 'hits': [{'id': d.id, 'source': d.metadata['source'],
                    'team': d.metadata['team'], 'cosine_distance': score} for d, score in hits]})
    output = {'recorded_at': datetime.now(timezone.utc).isoformat(),
        'model': MODEL, 'model_digest': digest, 'documents': len(chunks), 'dimensions': len(vectors[0]),
        'embedding_and_query_seconds': elapsed, 'questions': rows,
        'versions': {p: importlib.metadata.version(p) for p in ['langchain-postgres', 'langchain-core',
            'langchain-ollama', 'langchain-google-genai', 'langchain-text-splitters', 'pgvector', 'psycopg']},
        'vectors_sha256': hashlib.sha256((ROOT / 'vectors.json').read_bytes()).hexdigest()}
    (ROOT / 'library-run.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps(output, indent=2))

if __name__ == '__main__':
    main()
