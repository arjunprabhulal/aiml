"""Offline tests: recorded vectors and a fake server. No model is called."""
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
import embed_corpus
import embedder
import inspect_vectors
from embedder import MANIFEST, Embedder, EmbeddingError, query_text

HERE = Path(__file__).parent
DIM = MANIFEST['dimensions']


def unit(i: int) -> list[float]:
    vector = [0.0] * DIM
    vector[i % DIM] = 1.0
    return vector


class FakeServer:
    """Answers like Ollama; each embedding encodes its input's position, so order is checkable."""

    def __init__(self, digest=MANIFEST['ollama_digest'], dims=DIM, scale=1.0, error=None):
        self.digest, self.dims, self.scale, self.error, self.calls = digest, dims, scale, error, []

    def __call__(self, path, payload):
        self.calls.append((path, payload))
        if path == '/api/tags':
            return {'models': [{'name': MANIFEST['ollama_tag'], 'digest': self.digest}]}
        if self.error:
            raise EmbeddingError(self.error)
        offset = sum(len(p['input']) for _, p in self.calls[1:-1])
        vectors = [[x * self.scale for x in unit(offset + i)][:self.dims] + [0.0] * (self.dims - DIM)
                   for i in range(len(payload['input']))]
        return {'embeddings': vectors, 'prompt_eval_count': sum(len(t.split()) for t in payload['input'])}


class PipelineTest(unittest.TestCase):
    def test_recorded_report_matches_a_fresh_offline_run(self):
        self.assertEqual(inspect_vectors.report(), json.loads((HERE / 'inspection-result.json').read_text()))

    def test_index_matches_corpus_and_vectors(self):
        index, passages, vectors = inspect_vectors.load()
        self.assertEqual(index['ids'], [p['id'] for p in passages])
        self.assertEqual(len(vectors), index['count'])
        self.assertTrue(all(len(v) == DIM for v in vectors))
        self.assertEqual((HERE / 'vectors.f32').stat().st_size, index['count'] * DIM * 4)

    def test_stored_vectors_are_unit_length(self):
        _, _, vectors = inspect_vectors.load()
        for vector in vectors:
            self.assertAlmostEqual(math.sqrt(sum(x * x for x in vector)), 1.0, delta=1e-5)

    def test_changed_corpus_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = Path(folder)
            for name in ('corpus.json', 'index.json', 'vectors.f32', 'query-vectors.f32', 'query-vectors.json', 'drift.json', 'queries.json'):
                shutil.copy(HERE / name, copy / name)
            corpus = json.loads((copy / 'corpus.json').read_text())
            corpus['passages'][0]['text'] += ' Edited after embedding.'
            (copy / 'corpus.json').write_text(json.dumps(corpus))
            original = inspect_vectors.HERE
            inspect_vectors.HERE = copy
            try:
                with self.assertRaisesRegex(ValueError, 'does not match index.json'):
                    inspect_vectors.load()
            finally:
                inspect_vectors.HERE = original

    def test_passages_contain_no_page_markup(self):
        for passage in json.loads((HERE / 'corpus.json').read_text())['passages']:
            for marker in ('/>', '=>', '.map(', 'CodePanel', 'className', 'import '):
                self.assertNotIn(marker, passage['text'], passage['id'])

    def test_wrong_model_digest_is_refused_before_embedding(self):
        server = FakeServer(digest='sha256-other')
        with self.assertRaisesRegex(EmbeddingError, 'pinned digest'):
            Embedder(server)
        self.assertEqual([path for path, _ in server.calls], ['/api/tags'])

    def test_wrong_dimension_or_length_is_refused(self):
        with self.assertRaisesRegex(EmbeddingError, 'dimensions'):
            Embedder(FakeServer(dims=768)).documents(['text'])
        with self.assertRaisesRegex(EmbeddingError, 'unit-length'):
            Embedder(FakeServer(scale=2.0)).documents(['text'])

    def test_over_length_input_fails_instead_of_truncating(self):
        server = FakeServer(error='/api/embed returned HTTP 400: the input length exceeds the context length')
        with self.assertRaisesRegex(EmbeddingError, 'exceeds the context length'):
            Embedder(server).documents(['word ' * 40000])
        self.assertIs(server.calls[-1][1]['truncate'], False)

    def test_queries_carry_the_instruction_and_documents_do_not(self):
        server = FakeServer()
        model = Embedder(server)
        model.documents(['A passage.'])
        model.query('Where do API keys live?')
        self.assertEqual(server.calls[1][1]['input'], ['A passage.'])
        self.assertEqual(server.calls[2][1]['input'], [query_text('Where do API keys live?')])
        self.assertTrue(server.calls[2][1]['input'][0].startswith(f'Instruct: {MANIFEST["query_instruction"]}\nQuery:'))

    def test_batches_keep_input_order(self):
        server = FakeServer()
        vectors, tokens = Embedder(server).documents([f'passage {i}' for i in range(5)], batch_size=2)
        self.assertEqual([v.index(1.0) for v in vectors], [0, 1, 2, 3, 4])
        self.assertEqual(len(tokens), 3)

    def test_blank_input_and_bad_batch_size_are_rejected(self):
        model = Embedder(FakeServer())
        for action in (lambda: model.documents(['ok', '  ']), lambda: model.documents([]),
                       lambda: model.documents(['ok'], batch_size=0)):
            with self.assertRaises(EmbeddingError):
                action()

    def test_vector_file_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'v.f32'
            rows = [unit(3), unit(7)]
            embed_corpus.write_vectors(path, rows)
            self.assertEqual(embed_corpus.read_vectors(path, DIM), rows)
            path.write_bytes(path.read_bytes()[:-4])
            with self.assertRaisesRegex(ValueError, 'whole'):
                embed_corpus.read_vectors(path, DIM)


if __name__ == '__main__':
    unittest.main()
