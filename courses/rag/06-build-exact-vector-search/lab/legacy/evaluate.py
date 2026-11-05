"""Evaluate exact vector search on the 24 labeled questions, offline.

Compares three ways to rank the passages for each question:

vector          exact cosine ranking of the stored passage vectors
vector-lessons  the same ranking, keeping only each lesson's best passage
tf-idf          the TF-IDF retriever from the earlier build, unchanged

It also compares cosine, dot product and Euclidean distance. For unit-length
vectors they give the same order in exact arithmetic; the stored float32
vectors are unit length only to about six decimal places, so the report
records where the full orders differ. Scaling the vectors to different
lengths makes cosine and dot product disagree on the top 5.
"""
import json
from pathlib import Path
from lexical import rank as tfidf_rank
from search import VectorIndex, load_queries

HERE = Path(__file__).parent
K = 5


def query_vectors(index: VectorIndex, questions: list[dict]) -> tuple[list[list[float]], str]:
    """The questions embedded with the instruction, in queries.json order, and the build that embedded them."""
    rows = [q for q in load_queries(index) if q['instruction']]
    if [q['query'] for q in rows] != [q['id'] for q in questions]:
        raise ValueError('query-vectors.json rows do not follow queries.json')
    return [q['vector'] for q in rows], rows[0]['model_digest']


def measures(results: list[list[str]], questions: list[dict]) -> dict:
    """results[i] is the ordered list of lesson IDs returned for question i."""
    first = []
    for lessons, q in zip(results, questions):
        first.append(next((r for r, lesson in enumerate(lessons, 1) if lesson in q['relevant']), None))
    covered = sum(len(set(lessons[:K]) & set(q['relevant'])) for lessons, q in zip(results, questions))
    return {'questions_found_at_1': sum(r == 1 for r in first),
            'questions_found_at_5': sum(r is not None and r <= K for r in first),
            'mrr': round(sum(1 / r for r in first if r) / len(first), 3),
            'relevant_lessons_in_top_5': covered,
            'relevant_lessons_total': sum(len(q['relevant']) for q in questions),
            'mean_distinct_lessons_in_top_5': round(sum(len(set(lessons[:K])) for lessons in results) / len(results), 2),
            'first_relevant_rank': first}


def run() -> dict:
    index = VectorIndex()
    questions = json.loads((HERE / 'queries.json').read_text())['queries']
    vectors, digest = query_vectors(index, questions)
    texts = [p['text'] for p in index.passages]
    position = {text: i for i, text in enumerate(texts)}

    plain, grouped, lexical, top_k_agree, swaps = [], [], [], True, []
    for q, vector in zip(questions, vectors):
        everything = index.search(vector, digest, k=len(texts))
        plain.append([hit['lesson'] for hit in everything])
        grouped.append([hit['lesson'] for hit in index.search(vector, digest, k=K, one_per_lesson=True)])
        ranked_text = tfidf_rank(q['question'], texts)
        lexical.append([index.passages[position[text]]['lesson'] for _, text in ranked_text])
        orders = {m: [hit['id'] for hit in index.search(vector, digest, k=len(texts), metric=m)]
                  for m in ('cosine', 'dot', 'euclidean')}
        top_k_agree &= orders['cosine'][:K] == orders['dot'][:K] == orders['euclidean'][:K]
        cosine = dict(zip([p['id'] for p in index.passages], index.score(vector, 'cosine')))
        for metric in ('dot', 'euclidean'):
            where = next((r for r, (a, b) in enumerate(zip(orders['cosine'], orders[metric]), 1) if a != b), None)
            if where:
                a, b = orders['cosine'][where - 1], orders[metric][where - 1]
                swaps.append({'question': q['id'], 'metric': metric, 'first_difference_at_rank': where,
                              'cosine_gap': float(f'{abs(cosine[a] - cosine[b]):.2e}')})

    # Scale every stored vector by a different factor: direction is unchanged, length is not.
    scaled_changes = 0
    length_range = [round(min(index.lengths), 6), round(max(index.lengths), 6)]
    original, original_lengths = index.vectors, index.lengths
    index.vectors = [[x * (1 + (i % 7)) for x in v] for i, v in enumerate(original)]
    index.lengths = [n * (1 + (i % 7)) for i, n in enumerate(index.lengths)]
    for vector in vectors:
        top = {m: [h['id'] for h in index.search(vector, digest, k=K, metric=m)] for m in ('cosine', 'dot')}
        scaled_changes += top['cosine'] != top['dot']
    index.vectors, index.lengths = original, original_lengths

    per_question = []
    for i, q in enumerate(questions):
        per_question.append({'id': q['id'], 'question': q['question'], 'relevant': q['relevant'],
                             'vector_top': plain[i][:3], 'tf_idf_top': lexical[i][:3]})
    return {
        'k': K,
        'passages': len(texts),
        'questions': len(questions),
        'multiply_adds_per_query': len(texts) * index.dimensions,
        'measures': {'vector': measures(plain, questions), 'vector-lessons': measures(grouped, questions),
                     'tf-idf': measures(lexical, questions)},
        'stored_vector_length_range': length_range,
        'metrics_agree_on_top_5': top_k_agree,
        'full_order_differences': swaps,
        'questions_whose_top_5_differs_after_scaling': scaled_changes,
        'per_question': per_question,
    }


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
