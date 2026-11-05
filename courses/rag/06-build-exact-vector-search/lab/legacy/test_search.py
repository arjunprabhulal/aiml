"""Offline tests for exact vector search. No model server is needed."""
from array import array
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from search import SearchError, VectorIndex, load_queries

HERE = Path(__file__).parent
DIGEST = 'test-digest'


def tiny_index(folder: Path, rows: list[list[float]], lessons: list[str]) -> VectorIndex:
    """Write a small index with the same files and hashes as the real one."""
    passages = [{'id': f'p{i}', 'lesson': lesson, 'title': f'Passage {i}', 'text': f'text {i}'}
                for i, lesson in enumerate(lessons)]
    (folder / 'corpus.json').write_text(json.dumps({'passages': passages}))
    data = array('f', [x for row in rows for x in row])
    if sys.byteorder != 'little':
        data.byteswap()
    (folder / 'vectors.f32').write_bytes(data.tobytes())
    digest = lambda name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
    (folder / 'index.json').write_text(json.dumps({
        'model': {'dimensions': len(rows[0]), 'ollama_digest': DIGEST}, 'count': len(rows),
        'corpus_sha256': digest('corpus.json'), 'vectors_sha256': digest('vectors.f32')}))
    return VectorIndex(folder)


def unit(*values: float) -> list[float]:
    n = math.sqrt(sum(v * v for v in values))
    return [v / n for v in values]


class SearchTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_fixture_matches_recorded_result(self):
        output = subprocess.run([sys.executable, 'evaluate.py'], cwd=HERE, check=True,
                                capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), json.loads((HERE / 'evaluation-result.json').read_text()))

    def test_query_from_another_model_build_is_refused(self):
        index = tiny_index(self.folder, [unit(1, 0), unit(0, 1)], ['a', 'b'])
        with self.assertRaisesRegex(SearchError, 'different model build'):
            index.search(unit(1, 0), 'other-digest', k=1)

    def test_wrong_dimension_zero_or_nan_query_is_refused(self):
        index = tiny_index(self.folder, [unit(1, 0), unit(0, 1)], ['a', 'b'])
        for query in ([1.0, 0.0, 0.0], [0.0, 0.0], [float('nan'), 1.0]):
            with self.subTest(query=query), self.assertRaises(SearchError):
                index.search(query, DIGEST, k=1)

    def test_k_must_be_within_the_index(self):
        index = tiny_index(self.folder, [unit(1, 0), unit(0, 1)], ['a', 'b'])
        for k in (0, 3, True, 1.5):
            with self.subTest(k=k), self.assertRaises(SearchError):
                index.search(unit(1, 0), DIGEST, k=k)

    def test_ties_break_by_passage_position(self):
        same = unit(1, 1)
        index = tiny_index(self.folder, [unit(0, 1), same, same, same], ['a', 'b', 'c', 'd'])
        self.assertEqual([h['id'] for h in index.search(same, DIGEST, k=3)], ['p1', 'p2', 'p3'])

    def test_top_k_equals_the_full_sorted_ranking(self):
        index = VectorIndex()
        query = index.vectors[42]
        digest = index.record['model']['ollama_digest']
        full = index.search(query, digest, k=len(index.vectors))
        self.assertEqual(index.search(query, digest, k=7), full[:7])
        self.assertEqual(full[0]['id'], index.passages[42]['id'])
        scores = [h['score'] for h in full]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_one_result_per_lesson_keeps_each_lessons_best_passage(self):
        index = tiny_index(self.folder, [unit(1, 0.1), unit(1, 0.2), unit(0.1, 1), unit(1, 0.3)],
                           ['a', 'a', 'b', 'c'])
        hits = index.search(unit(1, 0), DIGEST, k=3, one_per_lesson=True)
        self.assertEqual([h['lesson'] for h in hits], ['a', 'c', 'b'])
        self.assertEqual(hits[0]['id'], 'p0')

    def test_metrics_agree_on_unit_vectors_and_not_on_scaled_ones(self):
        rows = [unit(1, 0.2), unit(0.6, 1), unit(1, 1)]
        index = tiny_index(self.folder, rows, ['a', 'b', 'c'])
        query = unit(1, 0.5)
        orders = {m: [h['id'] for h in index.search(query, DIGEST, k=3, metric=m)]
                  for m in ('cosine', 'dot', 'euclidean')}
        self.assertEqual(orders['cosine'], orders['dot'])
        self.assertEqual(orders['cosine'], orders['euclidean'])
        scaled = tiny_index(Path(tempfile.mkdtemp(dir=self.folder)),
                            [[x * f for x in row] for row, f in zip(rows, (1, 1, 3))], ['a', 'b', 'c'])
        self.assertNotEqual([h['id'] for h in scaled.search(query, DIGEST, k=3, metric='dot')],
                            [h['id'] for h in scaled.search(query, DIGEST, k=3, metric='cosine')])

    def test_changed_corpus_or_vectors_are_refused(self):
        tiny_index(self.folder, [unit(1, 0), unit(0, 1)], ['a', 'b'])
        corpus = json.loads((self.folder / 'corpus.json').read_text())
        corpus['passages'][0]['text'] = 'edited'
        (self.folder / 'corpus.json').write_text(json.dumps(corpus))
        with self.assertRaisesRegex(SearchError, 'embed it again'):
            VectorIndex(self.folder)
        tiny_index(self.folder, [unit(1, 0), unit(0, 1)], ['a', 'b'])
        (self.folder / 'vectors.f32').write_bytes((self.folder / 'vectors.f32').read_bytes()[:-4])
        with self.assertRaisesRegex(SearchError, 'does not match'):
            VectorIndex(self.folder)

    def test_stored_questions_from_another_build_or_changed_file_are_refused(self):
        index = tiny_index(self.folder, [unit(1, 0), unit(0, 1)], ['a', 'b'])
        data = array('f', unit(1, 0) + unit(0, 1))
        if sys.byteorder != 'little':
            data.byteswap()
        (self.folder / 'query-vectors.f32').write_bytes(data.tobytes())
        record = {'model_digest': DIGEST, 'vectors_sha256': hashlib.sha256(data.tobytes()).hexdigest(),
                  'rows': [{'query': 'q1', 'instruction': True}, {'query': 'q1', 'instruction': False}]}
        (self.folder / 'query-vectors.json').write_text(json.dumps(record))
        rows = load_queries(index, self.folder)
        self.assertEqual([(r['query'], r['instruction'], r['model_digest']) for r in rows],
                         [('q1', True, DIGEST), ('q1', False, DIGEST)])
        (self.folder / 'query-vectors.json').write_text(json.dumps({**record, 'model_digest': 'other-digest'}))
        with self.assertRaisesRegex(SearchError, 'different model build'):
            load_queries(index, self.folder)
        (self.folder / 'query-vectors.json').write_text(json.dumps({**record, 'vectors_sha256': '0' * 64}))
        with self.assertRaisesRegex(SearchError, 'does not match'):
            load_queries(index, self.folder)

    def test_unknown_metric_is_refused(self):
        index = tiny_index(self.folder, [unit(1, 0), unit(0, 1)], ['a', 'b'])
        with self.assertRaises(SearchError):
            index.search(unit(1, 0), DIGEST, k=1, metric='manhattan')


if __name__ == '__main__':
    unittest.main()
