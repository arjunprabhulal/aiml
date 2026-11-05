"""Inspect stored embeddings and record what they show.

Run `python inspect_vectors.py embed` once with the model server running: it
embeds the labeled questions with and without the query instruction, and
re-embeds a sample of passages to measure run-to-run drift. It writes
query-vectors.f32 with its provenance in query-vectors.json, and drift.json
(`python inspect_vectors.py drift` repeats only the drift measurement). `python inspect_vectors.py` (no argument)
then works offline from the stored files and prints the inspection report.
"""
from array import array
import json
import math
from pathlib import Path
import sys
from embed_corpus import read_vectors, sha256, write_vectors
from embedder import MANIFEST

HERE = Path(__file__).parent
PROBES = ['vectors-and-similarity#compare-meanings-instead-of-shared-words',
          'keyword-ranking#how-bm25-weighs-rare-terms-repeats-and-length',
          'build-isolated-contexts#problem']
DUPLICATE_THRESHOLD = 0.95
DRIFT_SAMPLE = 24


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def load():
    index = json.loads((HERE / 'index.json').read_text())
    corpus = json.loads((HERE / 'corpus.json').read_text())
    if sha256(HERE / 'corpus.json') != index['corpus_sha256'] or sha256(HERE / 'vectors.f32') != index['vectors_sha256']:
        raise ValueError('corpus.json or vectors.f32 does not match index.json; run embed_corpus.py again')
    vectors = read_vectors(HERE / 'vectors.f32', index['model']['dimensions'])
    if len(vectors) != index['count'] or len(corpus['passages']) != index['count']:
        raise ValueError('index, corpus and vectors disagree on the passage count')
    return index, corpus['passages'], vectors


def ranked(query: list[float], vectors: list[list[float]]) -> list[tuple[float, int]]:
    """Exact cosine ranking. Vectors are unit length, so the dot product is the cosine."""
    return sorted(((dot(query, v), i) for i, v in enumerate(vectors)), key=lambda p: (-p[0], p[1]))


def lesson_rank(order: list[tuple[float, int]], passages: list[dict], relevant: list[str]) -> int | None:
    """1-based rank of the first passage from a relevant lesson."""
    return next((rank for rank, (_, i) in enumerate(order, 1) if passages[i]['lesson'] in relevant), None)


def float32(vector: list[float]) -> list[float]:
    """The vector as vectors.f32 stores it: each coordinate rounded to float32."""
    return array('f', vector).tolist()


def cosine(a: list[float], b: list[float]) -> float:
    return math.fsum(x * y for x, y in zip(a, b)) / math.sqrt(math.fsum(x * x for x in a) * math.fsum(y * y for y in b))


def query_record(queries: list[dict], digest: str) -> dict:
    """Provenance stored beside query-vectors.f32: the model build and, per row, the question and instruction flag."""
    return {'model_digest': digest, 'query_instruction': MANIFEST['query_instruction'],
            'vectors_sha256': sha256(HERE / 'query-vectors.f32'),
            'rows': [{'query': q['id'], 'instruction': flag} for flag in (True, False) for q in queries]}


def embed_queries():
    from embedder import Embedder
    queries = json.loads((HERE / 'queries.json').read_text())['queries']
    embedder = Embedder()
    rows = [embedder.query(q['question'], instruction=True) for q in queries]
    rows += [embedder.query(q['question'], instruction=False) for q in queries]
    write_vectors(HERE / 'query-vectors.f32', rows)
    record = query_record(queries, MANIFEST['ollama_digest'])
    (HERE / 'query-vectors.json').write_text(json.dumps(record, indent=2) + '\n')


def measure_drift():
    """Re-embed a sample in batches and compare with the stored vectors after the same float32 rounding."""
    from embedder import Embedder
    index, passages, vectors = load()
    step = max(1, len(passages) // DRIFT_SAMPLE)
    sample = list(range(0, len(passages), step))[:DRIFT_SAMPLE]
    again, _ = Embedder().documents([passages[i]['text'] for i in sample], batch_size=8)
    rounded = [float32(v) for v in again]
    drift = {'sample_ids': [passages[i]['id'] for i in sample],
             'compared_as': 'float32, as vectors.f32 stores them',
             'identical_vectors': sum(vectors[i] == v for i, v in zip(sample, rounded)),
             'max_abs_difference': max(abs(a - b) for i, v in zip(sample, rounded) for a, b in zip(vectors[i], v)),
             'min_cosine': min(cosine(vectors[i], v) for i, v in zip(sample, rounded)),
             'max_abs_difference_before_rounding': max(abs(a - b) for i, v in zip(sample, again)
                                                      for a, b in zip(vectors[i], v)),
             'note': 'stored passage vectors were embedded one at a time; the repeat used batches of 8'}
    (HERE / 'drift.json').write_text(json.dumps(drift, indent=2) + '\n')


def report() -> dict:
    index, passages, vectors = load()
    queries = json.loads((HERE / 'queries.json').read_text())['queries']
    norms = [math.sqrt(dot(v, v)) for v in vectors]
    position = {p['id']: i for i, p in enumerate(passages)}

    neighbors = {}
    for probe in PROBES:
        order = ranked(vectors[position[probe]], vectors)
        neighbors[probe] = [{'id': passages[i]['id'], 'cosine': round(score, 4)} for score, i in order[1:6]]

    duplicates = [(round(dot(vectors[i], vectors[j]), 4), passages[i]['id'], passages[j]['id'])
                  for i in range(len(vectors)) for j in range(i + 1, len(vectors))
                  if dot(vectors[i], vectors[j]) >= DUPLICATE_THRESHOLD]
    duplicates.sort(key=lambda d: (-d[0], d[1], d[2]))

    record = json.loads((HERE / 'query-vectors.json').read_text())
    if sha256(HERE / 'query-vectors.f32') != record['vectors_sha256'] or record['model_digest'] != index['model']['ollama_digest']:
        raise ValueError('query-vectors.f32 does not match query-vectors.json or another model build made it')
    query_vectors = read_vectors(HERE / 'query-vectors.f32', index['model']['dimensions'])
    with_instruction, without = query_vectors[:len(queries)], query_vectors[len(queries):]
    rows = []
    for q, a, b in zip(queries, with_instruction, without):
        order_a, order_b = ranked(a, vectors), ranked(b, vectors)
        rows.append({'id': q['id'], 'question': q['question'],
                     'rank_with_instruction': lesson_rank(order_a, passages, q['relevant']),
                     'rank_without_instruction': lesson_rank(order_b, passages, q['relevant']),
                     'top_with_instruction': passages[order_a[0][1]]['id']})

    def summary(key):
        ranks = [r[key] for r in rows]
        return {'questions_found_at_1': sum(r == 1 for r in ranks), 'questions_found_at_5': sum(r is not None and r <= 5 for r in ranks),
                'mrr': round(sum(1 / r for r in ranks if r) / len(ranks), 3), 'queries': len(ranks)}

    tokens = index['tokens']
    return {
        'model': index['model'],
        'passages': index['count'],
        'tokens': {'total': sum(tokens), 'min': min(tokens), 'median': sorted(tokens)[len(tokens) // 2],
                   'max': max(tokens)},
        'norms': {'min': round(min(norms), 6), 'max': round(max(norms), 6)},
        'nearest_neighbors': neighbors,
        'near_duplicates': {'threshold': DUPLICATE_THRESHOLD, 'pairs': len(duplicates),
                            'top': [{'cosine': c, 'a': a, 'b': b} for c, a, b in duplicates[:6]]},
        'query_instruction': {'with': summary('rank_with_instruction'),
                              'without': summary('rank_without_instruction'), 'per_query': rows},
        'drift': json.loads((HERE / 'drift.json').read_text()),
    }


if __name__ == '__main__':
    if sys.argv[1:] == ['embed']:
        embed_queries()
        measure_drift()
    elif sys.argv[1:] == ['drift']:
        measure_drift()
    else:
        print(json.dumps(report(), indent=2))
