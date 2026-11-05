"""Record three Gemini answers over retrieved internal developer documentation."""
from datetime import datetime, timezone
import json
from pathlib import Path
from library import documents, RecordedEmbeddings, vector_store, answer_question
from pg_cluster import Cluster
ROOT = Path(__file__).parent

def main():
    saved = json.loads((ROOT / 'vectors.json').read_text())
    questions = json.loads((ROOT / 'questions.json').read_text())
    requested = [questions[0], questions[2], {'question': 'Who approves production deployments on Fridays?', 'team': 'platform'}]
    # The last question deliberately has no source answer; embed it using the same adapter.
    from library import DocsEmbeddings, MODEL
    missing = requested[-1]['question']
    if missing not in saved['queries']:
        saved['queries'][missing] = DocsEmbeddings(model=MODEL).embed_query(missing)
        (ROOT / 'generation-vectors.json').write_text(json.dumps(saved, indent=2) + '\n')
    results = []
    with Cluster() as pg:
        with vector_store(pg.url, RecordedEmbeddings(saved)) as store:
            chunks = documents()
            store.add_documents(chunks, ids=[d.id for d in chunks])
            for case in requested:
                retrieved = store.similarity_search(case['question'], k=3, filter={'team': case['team']})
                results.append({'question': case['question'], 'team': case['team'],
                                **answer_question(case['question'], retrieved)})
    record = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'model': 'gemini-3.8-flash',
              'sampling': 'provider defaults', 'runs_per_question': 1, 'results': results}
    (ROOT / 'generation-run.json').write_text(json.dumps(record, indent=2, default=str) + '\n')
    print(json.dumps(record, indent=2, default=str))
if __name__ == '__main__': main()
