"""Compare exact search, the IVF index from the previous build, and pgvector.

    PGVECTOR_URL=postgresql://user@host:port/db python compare.py live --replace
        Needs PostgreSQL with the pgvector extension and pg8000. Loads the
        passages into the schema aiml_vector_compare (--replace drops it
        first), builds the indexes, runs every setting on the 48 question
        vectors, and repeats this from scratch 5 times, because pgvector's
        index builds are not repeatable. Writes the top 5 of every search,
        the query plans and sizes to pgvector-results.json.

    python compare.py
        Offline, standard library only. Recomputes exact search and the IVF
        index, and summarizes every method against exact search. The output
        is recorded in evaluation-result.json.
"""
from array import array
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
from ivf import IVFIndex
from search import VectorIndex, load_queries

HERE = Path(__file__).parent
K = 5
SCHEMA = 'aiml_vector_compare'
BUILDS = 5
FORCE = {'enable_seqscan': 'off'}
CONFIGS = {
    'pgvector, no index': (None, {}),
    **{f'pgvector IVFFlat, 16 lists, {p} probe{"s" * (p > 1)}': (('ivfflat', {'lists': 16}), {'ivfflat.probes': p, **FORCE})
       for p in (1, 2, 4, 16)},
    **{f'pgvector HNSW, ef_search {e}': (('hnsw', {}), {'hnsw.ef_search': e, **FORCE}) for e in (10, 20, 40)},
}
FILTERS = {'Builds only': {'kind': 'build'}, 'Programming foundations topic': {'topic': 'Programming foundations'}}
FILTERED = {  # name: (settings, keep the B-tree indexes on kind and topic)
    'pgvector, HNSW and B-tree indexes': ({'hnsw.ef_search': 40, **FORCE}, True),
    'pgvector, HNSW only, ef_search 40': ({'hnsw.ef_search': 40, 'hnsw.iterative_scan': 'off', **FORCE}, False),
    'pgvector, HNSW only, iterative scan': ({'hnsw.ef_search': 40, 'hnsw.iterative_scan': 'strict_order', **FORCE}, False),
}


def load_inputs():
    base = VectorIndex()
    # All 48 stored question vectors: the 24 questions with the instruction, then without it.
    vectors = [q['vector'] for q in load_queries(base)]
    questions = json.loads((HERE / 'queries.json').read_text())['queries']
    lessons = json.loads((HERE / 'lesson-metadata.json').read_text())['lessons']
    return base, vectors, questions, lessons


def plan_summary(plan) -> str:
    """'Index Scan using passages_embedding' or 'Seq Scan', from EXPLAIN (FORMAT JSON)."""
    node = plan[0]['Plan']
    while node.get('Plans') and node['Node Type'] in ('Limit', 'Sort', 'Result'):
        node = node['Plans'][0]
    if node['Node Type'] == 'Bitmap Heap Scan':
        node = {**node, 'Index Name': node['Plans'][0].get('Index Name')}
    return node['Node Type'] + (f" using {node['Index Name']}" if node.get('Index Name') else '')


def live(replace: bool, builds: int) -> dict:
    """Build the store and its indexes `builds` times from scratch and record every search."""
    import pg8000.dbapi
    from pgvector_store import PgvectorStore, parse_vector

    url = urlparse(os.environ['PGVECTOR_URL'])
    conn = pg8000.dbapi.connect(user=url.username, password=url.password, host=url.hostname,
                                port=url.port or 5432, database=url.path.lstrip('/'))
    base, vectors, questions, lessons = load_inputs()
    digest = load_queries(base)[0]['model_digest']
    row_of = {p['id']: i for i, p in enumerate(base.passages)}
    passages = [{**p, **lessons[p['lesson']]} for p in base.passages]
    record = {'builds': []}
    for build in range(builds):
        if replace or build:
            cursor = conn.cursor()
            cursor.execute(f'DROP SCHEMA IF EXISTS {SCHEMA} CASCADE')
            conn.commit()
        store = PgvectorStore.create(conn, SCHEMA, digest, base.dimensions)
        store.add(passages, base.vectors, digest)
        first = build == 0
        if first:
            stored = array('f', [x for (text,) in store.fetch(f'SELECT embedding::text FROM {SCHEMA}.passages ORDER BY row', [])
                                 for x in parse_vector(text)])
            if sys.byteorder != 'little':
                stored.byteswap()
            record.update({
                'server': {
                    'postgresql': store.fetch("SELECT current_setting('server_version')", [])[0][0],
                    'pgvector': store.fetch("SELECT extversion FROM pg_extension WHERE extname = 'vector'", [])[0][0],
                    'client': f'pg8000 {pg8000.__version__}'},
                'rows': store.fetch(f'SELECT count(*) FROM {SCHEMA}.passages', [])[0][0],
                'vectors_round_trip_exact': hashlib.sha256(stored.tobytes()).hexdigest() == base.record['vectors_sha256'],
                'sizes': {}, 'plans': {}, 'planner_choice_without_forcing': {},
                'filtered_plans': {label: {} for label in FILTERS}})

        def rows(hits):  # results are stored as passage positions to keep the file small
            return [row_of[h['id']] for h in hits]

        results, current = {}, None
        for name, (index, settings) in CONFIGS.items():
            wanted = index[0] if index else 'none'
            if wanted != current:
                store.create_index(index[0], **index[1]) if index else store.drop_index()
                current = wanted
                if first:
                    record['sizes'][wanted] = store.sizes()
                    plan = store.search(vectors[0], digest, k=K, explain=True)
                    record['planner_choice_without_forcing'][wanted] = plan_summary(plan)
            if first:
                record['plans'][name] = plan_summary(store.search(vectors[0], digest, k=K, settings=settings,
                                                                  explain=True))
            results[name] = [rows(store.search(v, digest, k=K, settings=settings)) for v in vectors]

        # Filtered searches, first with the B-tree indexes on kind and topic, then with HNSW alone.
        filtered = {label: {} for label in FILTERS}
        for name, (settings, metadata_indexes) in FILTERED.items():
            if not metadata_indexes:
                store.drop_metadata_indexes()
            for label, where in FILTERS.items():
                if first:
                    plan = store.search(vectors[0], digest, k=K, where=where, settings=settings, explain=True)
                    record['filtered_plans'][label][name] = plan_summary(plan)
                filtered[label][name] = [rows(store.search(v, digest, k=K, where=where, settings=settings))
                                         for v in vectors]
        record['builds'].append({'results': results, 'filtered': filtered})
    conn.close()
    return record


def summary(results: list[list[str]], exact: list[list[str]], questions, lessons_of: dict, scored=None) -> dict:
    n = len(results)
    out = {
        'recall_at_1': round(sum(bool(r) and r[0] == e[0] for r, e in zip(results, exact)) / n, 3),
        'recall_at_5': round(sum(len(set(r) & set(e)) / K for r, e in zip(results, exact)) / n, 3),
        'same_order_as_exact': sum(r == e for r, e in zip(results, exact)),
        'mean_results': round(sum(map(len, results)) / n, 2),
        'searches_with_fewer_than_5': sum(len(r) < K for r in results),
        'questions_with_a_relevant_lesson': sum(any(lessons_of[i] in q['relevant'] for i in r)
                                                for r, q in zip(results, questions)),
    }
    if scored is not None:
        out['mean_vectors_scored'] = round(sum(scored) / n, 1)
    return out


def run() -> dict:
    base, vectors, questions, lessons = load_inputs()
    digest = load_queries(base)[0]['model_digest']
    recorded = json.loads((HERE / 'pgvector-results.json').read_text())
    lessons_of = {p['id']: p['lesson'] for p in base.passages}
    full = [[h['id'] for h in base.search(v, digest, k=len(base.vectors))] for v in vectors]
    exact = [ranking[:K] for ranking in full]

    methods = {'Exact search (search.py)': summary(exact, exact, questions, lessons_of)}
    # Our IVF: the saved build (seed 0) first, then four more seeds for the range over builds.
    indexes = [IVFIndex.load(base)] + [IVFIndex.build(base, 16, seed=seed) for seed in (1, 2, 3, 4)]
    for nprobe in (1, 2, 4, 16):
        per_build = []
        for index in indexes:
            found = [index.search(v, digest, k=K, nprobe=nprobe) for v in vectors]
            per_build.append(summary([[h['id'] for h in hits] for hits, _ in found], exact, questions, lessons_of,
                                     [s for _, s in found]))
        values = [b['recall_at_5'] for b in per_build]
        methods[f'Our IVF, 16 lists, {nprobe} probe{"s" * (nprobe > 1)}'] = {
            **per_build[0], 'recall_at_5_over_builds': [min(values), max(values)]}
    ids = [p['id'] for p in base.passages]
    builds = [{'results': {n: [[ids[i] for i in r] for r in rs] for n, rs in b['results'].items()},
               'filtered': {f: {n: [[ids[i] for i in r] for r in rs] for n, rs in d.items()}
                            for f, d in b['filtered'].items()}} for b in recorded['builds']]

    def spread(per_build: list[dict]) -> dict:
        """The first build's summary, plus the range of recall@5 over all builds."""
        values = [s['recall_at_5'] for s in per_build]
        return {**per_build[0], 'recall_at_5_over_builds': [min(values), max(values)]}

    for name in builds[0]['results']:
        methods[name] = spread([summary(b['results'][name], exact, questions, lessons_of) for b in builds])

    filtered = {}
    for label, where in FILTERS.items():
        field, value = next(iter(where.items()))
        keep = {p['id'] for p in base.passages if lessons[p['lesson']][field] == value}
        truth = [[i for i in ranking if i in keep][:K] for ranking in full]
        filtered[label] = {'matching_passages': len(keep),
                           'Pre-filtered exact search': summary(truth, truth, questions, lessons_of)}
        for name in builds[0]['filtered'][label]:
            for b in builds:
                assert all(i in keep for r in b['filtered'][label][name] for i in r), f'{name} left the filter'
            filtered[label][name] = spread([summary(b['filtered'][label][name], truth, questions, lessons_of)
                                            for b in builds])

    return {
        'k': K,
        'searches': len(vectors),
        'pgvector_builds': len(recorded['builds']),
        'labeled_questions': len(questions),
        'server': recorded['server'],
        'rows': recorded['rows'],
        'vectors_round_trip_exact': recorded['vectors_round_trip_exact'],
        'sizes': recorded['sizes'],
        'raw_vector_bytes': len(base.vectors) * base.dimensions * 4,
        'planner_choice_without_forcing': recorded['planner_choice_without_forcing'],
        'plans': recorded['plans'],
        'filtered_plans': recorded['filtered_plans'],
        'methods': methods,
        'filtered': filtered,
    }


if __name__ == '__main__':
    if sys.argv[1:2] == ['live']:
        result = live(replace='--replace' in sys.argv, builds=BUILDS)
        (HERE / 'pgvector-results.json').write_text(json.dumps(result, separators=(',', ':')) + '\n')
        print(f"recorded {len(result['builds'])} builds")
    else:
        print(json.dumps(run(), indent=2))
