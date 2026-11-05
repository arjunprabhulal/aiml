"""Exact vector search over the stored passage vectors.

Standard library only. VectorIndex loads vectors.f32 with index.json, checks
the hashes and the model digest, and ranks every stored vector against a
query vector. Nothing is approximated: every row is scored.
"""
from array import array
import hashlib
import heapq
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).parent
METRICS = ('cosine', 'dot', 'euclidean')


class SearchError(ValueError):
    """The index, the query vector or a search setting is unusable."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def length(a) -> float:
    return math.sqrt(dot(a, a))


class VectorIndex:
    def __init__(self, folder: Path = HERE):
        self.record = json.loads((folder / 'index.json').read_text())
        self.passages = json.loads((folder / 'corpus.json').read_text())['passages']
        if sha256(folder / 'corpus.json') != self.record['corpus_sha256']:
            raise SearchError('corpus.json changed after embedding; embed it again')
        if sha256(folder / 'vectors.f32') != self.record['vectors_sha256']:
            raise SearchError('vectors.f32 does not match index.json')
        self.dimensions = self.record['model']['dimensions']
        rows = array('f')
        rows.frombytes((folder / 'vectors.f32').read_bytes())
        if sys.byteorder != 'little':
            rows.byteswap()
        if len(rows) != self.record['count'] * self.dimensions or len(self.passages) != self.record['count']:
            raise SearchError('index.json, corpus.json and vectors.f32 disagree on size')
        self.vectors = [rows[i:i + self.dimensions].tolist() for i in range(0, len(rows), self.dimensions)]
        self.lengths = [length(v) for v in self.vectors]

    def check_query(self, query: list[float], model_digest: str):
        """A query vector is comparable only if the same model build produced it."""
        if model_digest != self.record['model']['ollama_digest']:
            raise SearchError('the query was embedded by a different model build than the index')
        if len(query) != self.dimensions:
            raise SearchError(f'query has {len(query)} dimensions; the index has {self.dimensions}')
        if not all(math.isfinite(x) for x in query) or length(query) == 0:
            raise SearchError('query vector must be finite and nonzero')

    def score(self, query: list[float], metric: str = 'cosine') -> list[float]:
        """One score per stored vector; higher is better for every metric."""
        if metric not in METRICS:
            raise SearchError(f'metric must be one of {METRICS}')
        if metric == 'dot':
            return [dot(query, v) for v in self.vectors]
        if metric == 'cosine':
            q = length(query)
            return [dot(query, v) / (q * n) for v, n in zip(self.vectors, self.lengths)]
        # Euclidean distance, negated so that a smaller distance ranks higher.
        return [-math.sqrt(sum((x - y) ** 2 for x, y in zip(query, v))) for v in self.vectors]

    def search(self, query: list[float], model_digest: str, k: int = 5, metric: str = 'cosine',
               one_per_lesson: bool = False) -> list[dict]:
        """Top k passages. Ties break by passage position, so results are repeatable."""
        self.check_query(query, model_digest)
        if type(k) is not int or not 1 <= k <= len(self.vectors):
            raise SearchError(f'k must be an integer from 1 to {len(self.vectors)}')
        scores = self.score(query, metric)
        if not one_per_lesson:
            top = heapq.nsmallest(k, range(len(scores)), key=lambda i: (-scores[i], i))
        else:
            # Keep only each lesson's best passage, then take the top k lessons.
            best = {}
            for i in sorted(range(len(scores)), key=lambda i: (-scores[i], i)):
                best.setdefault(self.passages[i]['lesson'], i)
                if len(best) == k:
                    break
            top = list(best.values())
        return [{'rank': r, 'id': self.passages[i]['id'], 'lesson': self.passages[i]['lesson'],
                 'title': self.passages[i]['title'], 'score': round(scores[i], 6)} for r, i in enumerate(top, 1)]


def load_queries(index: VectorIndex, folder: Path = HERE) -> list[dict]:
    """Stored question vectors with their provenance from query-vectors.json.

    Each row says which question it embeds, whether the query instruction was
    used, and which model build produced it. A file whose hash does not match,
    or that another model build produced, is refused.
    """
    record = json.loads((folder / 'query-vectors.json').read_text())
    if sha256(folder / 'query-vectors.f32') != record['vectors_sha256']:
        raise SearchError('query-vectors.f32 does not match query-vectors.json')
    if record['model_digest'] != index.record['model']['ollama_digest']:
        raise SearchError('the stored questions were embedded by a different model build than the index')
    rows = array('f')
    rows.frombytes((folder / 'query-vectors.f32').read_bytes())
    if sys.byteorder != 'little':
        rows.byteswap()
    d = index.dimensions
    if len(rows) != len(record['rows']) * d:
        raise SearchError('query-vectors.f32 and query-vectors.json disagree on the row count')
    return [{**row, 'model_digest': record['model_digest'], 'vector': rows[i * d:(i + 1) * d].tolist()}
            for i, row in enumerate(record['rows'])]


def search_text(question: str, k: int = 5, one_per_lesson: bool = False) -> list[dict]:
    """Embed a question with the pinned model and search. Needs the Ollama server."""
    from embedder import MANIFEST, Embedder
    index = VectorIndex()
    vector = Embedder().query(question)
    return index.search(vector, MANIFEST['ollama_digest'], k=k, one_per_lesson=one_per_lesson)


if __name__ == '__main__':
    question = ' '.join(sys.argv[1:]) or 'How does a word that appears everywhere count for less?'
    for hit in search_text(question):
        print(f'{hit["rank"]}. {hit["score"]:.4f}  {hit["id"]}')
