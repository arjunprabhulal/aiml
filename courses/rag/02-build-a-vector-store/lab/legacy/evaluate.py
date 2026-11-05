"""Evaluate the store on the 24 labeled questions, offline.

1. Load the store into a temporary file, close it and open it again, then
   check that it returns what exact search from the previous build returns.
2. Run each question with metadata filters, three ways:

   pre        select matching rows, then score them
   post-5     score every row, keep the best 5, then drop rows that fail the filter
   post-20    the same with the best 20 kept before filtering

   and count how many results each returns and whether a relevant lesson
   appears in the top 5.
"""
import json
from pathlib import Path
import tempfile
from load_store import build
from search import VectorIndex, load_queries
from store import VectorStore

HERE = Path(__file__).parent
K = 5
FIXED_FILTERS = {
    'Builds only': {'kind': 'build'},
    'Programming foundations topic': {'topic': 'Programming foundations'},
    'Foundations of 7 minutes or less': {'kind': 'foundation', 'minutes': {'lte': 7}},
}
METHODS = {'pre': {'filtering': 'pre'}, 'post-5': {'filtering': 'post', 'candidates': K},
           'post-20': {'filtering': 'post', 'candidates': 4 * K}}


def query_vectors(index: VectorIndex, questions: list[dict]) -> tuple[list[list[float]], str]:
    """The questions embedded with the instruction, in queries.json order, and the build that embedded them."""
    rows = [q for q in load_queries(index) if q['instruction']]
    if [q['query'] for q in rows] != [q['id'] for q in questions]:
        raise ValueError('query-vectors.json rows do not follow queries.json')
    return [q['vector'] for q in rows], rows[0]['model_digest']


def summarize(store, vectors, digest, filters, matching, relevant=None) -> dict:
    """filters[i] is the filter for question i; matching(f) says whether a passage passes it."""
    report = {}
    for name, options in METHODS.items():
        returned, short, empty, found = [], 0, 0, 0
        for i, (vector, where) in enumerate(zip(vectors, filters)):
            hits = store.search(vector, digest, k=K, where=where, **options)
            assert all(matching(h, where) for h in hits)
            returned.append(len(hits))
            short += len(hits) < K
            empty += not hits
            if relevant:
                found += any(h['lesson'] in relevant[i] for h in hits)
        report[name] = {'mean_results': round(sum(returned) / len(returned), 2),
                        'questions_with_fewer_than_5': short, 'questions_with_none': empty}
        if relevant:
            report[name]['questions_with_a_relevant_lesson'] = found
    return report


def passes(hit: dict, where: dict) -> bool:
    for field, condition in where.items():
        if not isinstance(condition, dict):
            condition = {'eq': condition}
        for op, value in condition.items():
            v = hit[field]
            ok = {'eq': lambda: v == value, 'in': lambda: v in value,
                  'gte': lambda: v >= value, 'lte': lambda: v <= value}[op]()
            if not ok:
                return False
    return True


def run() -> dict:
    questions = json.loads((HERE / 'queries.json').read_text())['queries']
    lessons = json.loads((HERE / 'lesson-metadata.json').read_text())['lessons']
    index = VectorIndex(HERE)
    vectors, digest = query_vectors(index, questions)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'store.sqlite'
        build(path).close()
        store = VectorStore.open(path)

        same_top_5 = sum([h['id'] for h in store.search(v, digest, k=K)] ==
                         [h['id'] for h in index.search(v, digest, k=K)] for v in vectors)
        # Pre-filtering must equal exact search followed by filtering the complete ranking.
        exact_filtered = 0
        everything = [index.search(v, digest, k=len(index.vectors)) for v in vectors]
        for where in FIXED_FILTERS.values():
            for v, ranking in zip(vectors, everything):
                expected = [h['id'] for h in ranking if passes({**h, **lessons[h['lesson']]}, where)][:K]
                exact_filtered += [h['id'] for h in store.search(v, digest, k=K, where=where)] == expected

        topic_filters = [{'topic': lessons[q['relevant'][0]]['topic']} for q in questions]
        relevant = [set(q['relevant']) for q in questions]
        unfiltered_found = sum(any(h['lesson'] in relevant[i] for h in store.search(v, digest, k=K))
                               for i, v in enumerate(vectors))
        report = {
            'k': K,
            'questions': len(questions),
            'stored_passages': store.count(),
            'vectors_match_source_file': store.vectors_sha256() == index.record['vectors_sha256'],
            'questions_with_same_top_5_as_exact_search': same_top_5,
            'filtered_searches_equal_to_filtering_the_exact_ranking': exact_filtered,
            'filtered_searches_checked': len(FIXED_FILTERS) * len(questions),
            'topic_of_the_relevant_lesson': {
                'rows_scored_pre_mean': round(sum(store.count(f) for f in topic_filters) / len(questions), 1),
                'unfiltered_questions_with_a_relevant_lesson': unfiltered_found,
                **summarize(store, vectors, digest, topic_filters, passes, relevant),
            },
            'fixed_filters': {},
        }
        for name, where in FIXED_FILTERS.items():
            report['fixed_filters'][name] = {'filter': where, 'matching_passages': store.count(where),
                                             **summarize(store, vectors, digest, [where] * len(questions), passes)}
        store.close()
    return report


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
