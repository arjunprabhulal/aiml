"""A small inverted file (IVF) index for approximate nearest-neighbor search.

Training groups the stored vectors into `nlist` lists with k-means; each list
has a centroid. A search scores the query against the centroids, opens the
`nprobe` closest lists and scores only the vectors in them. With
nprobe == nlist every vector is scored and the result equals exact search.

Standard library only. The exact search from the previous build (search.py)
loads and checks the stored vectors.
"""
from array import array
import hashlib
import heapq
import json
import math
from operator import mul
from pathlib import Path
import random
import sys
from search import SearchError, VectorIndex

HERE = Path(__file__).parent
FORMAT_VERSION = 1
SAME = 1e-5  # squared distance below which two float32 unit vectors count as the same point


def dot(a, b) -> float:
    return sum(map(mul, a, b))


def as_float32(v: list[float]) -> list[float]:
    """Round to float32 so a saved and reloaded centroid is the same number."""
    return array('f', v).tolist()


def unit(v: list[float]) -> list[float]:
    n = math.sqrt(dot(v, v))
    return as_float32([x / n for x in v])


def restart_empty_lists(assignment: list[int], sims: list[list[float]], nlist: int) -> list[int]:
    """Give every empty list one vector: the one that fits its current list worst.

    sims[i][c] is vector i's similarity to centroid c. Only lists with more
    than one vector give one up, so no list is emptied to fill another.
    """
    new = list(assignment)
    sizes = [new.count(c) for c in range(nlist)]
    for c in range(nlist):
        if sizes[c] == 0:
            worst = min((i for i in range(len(new)) if sizes[new[i]] > 1), key=lambda i: (sims[i][new[i]], i))
            sizes[new[worst]] -= 1
            new[worst], sizes[c] = c, 1
    return new


def kmeans(vectors: list[list[float]], nlist: int, seed: int, max_iterations: int) -> tuple:
    """k-means on unit vectors with cosine similarity and k-means++ starting points.

    Returns (centroids, assignment, iterations, converged). Centroids are
    rescaled to length 1 so that the dot product with them is a cosine.
    """
    rng = random.Random(seed)
    n = len(vectors)
    chosen = [rng.randrange(n)]
    nearest = [dot(v, vectors[chosen[0]]) for v in vectors]
    while len(chosen) < nlist:
        # k-means++: pick the next start with probability proportional to its
        # squared distance from the nearest start (2 - 2 cos for unit vectors).
        weights = [d if (d := 2 - 2 * s) > SAME else 0.0 for s in nearest]
        pick, total = rng.random() * sum(weights), 0.0
        if pick == 0:
            raise SearchError(f'fewer than {nlist} distinct vectors; use fewer lists')
        for i, w in enumerate(weights):
            total += w
            if w > 0 and total >= pick:
                break
        chosen.append(i)
        nearest = [max(s, dot(v, vectors[i])) for s, v in zip(nearest, vectors)]
    centroids = [unit(vectors[i]) for i in chosen]

    assignment, converged = None, False
    for iteration in range(1, max_iterations + 1):
        sims = [[dot(v, c) for c in centroids] for v in vectors]
        new = restart_empty_lists([max(range(nlist), key=lambda c: (row[c], -c)) for row in sims], sims, nlist)
        if new == assignment:
            converged = True
            break
        assignment = new
        for c in range(nlist):
            members = [vectors[i] for i in range(n) if assignment[i] == c]
            centroids[c] = unit([sum(column) for column in zip(*members)])
    return centroids, assignment, iteration, converged


class IVFIndex:
    def __init__(self, base: VectorIndex, centroids: list[list[float]], lists: list[list[int]], settings: dict):
        self.base, self.centroids, self.lists, self.settings = base, centroids, lists, settings
        self.nlist = len(centroids)

    @classmethod
    def build(cls, base: VectorIndex, nlist: int, seed: int = 0, max_iterations: int = 20) -> 'IVFIndex':
        n = len(base.vectors)
        if type(nlist) is not int or not 1 <= nlist <= n:
            raise SearchError(f'nlist must be an integer from 1 to {n}')
        centroids, assignment, iterations, converged = kmeans(base.vectors, nlist, seed, max_iterations)
        lists = [[i for i in range(n) if assignment[i] == c] for c in range(nlist)]
        settings = {'nlist': nlist, 'seed': seed, 'max_iterations': max_iterations,
                    'iterations': iterations, 'converged': converged}
        return cls(base, centroids, lists, settings)

    def search(self, query: list[float], model_digest: str, k: int = 5, nprobe: int = 1) -> tuple[list[dict], int]:
        """Top k from the nprobe closest lists, and how many vectors were scored."""
        self.base.check_query(query, model_digest)
        if type(k) is not int or not 1 <= k <= len(self.base.vectors):
            raise SearchError(f'k must be an integer from 1 to {len(self.base.vectors)}')
        if type(nprobe) is not int or not 1 <= nprobe <= self.nlist:
            raise SearchError(f'nprobe must be an integer from 1 to {self.nlist}')
        probed = heapq.nsmallest(nprobe, range(self.nlist), key=lambda c: (-dot(query, self.centroids[c]), c))
        candidates = sorted(i for c in probed for i in self.lists[c])
        q = math.sqrt(dot(query, query))
        scores = {i: dot(query, self.base.vectors[i]) / (q * self.base.lengths[i]) for i in candidates}
        top = heapq.nsmallest(k, candidates, key=lambda i: (-scores[i], i))
        passages = self.base.passages
        hits = [{'rank': r, 'id': passages[i]['id'], 'lesson': passages[i]['lesson'],
                 'title': passages[i]['title'], 'score': round(scores[i], 6)} for r, i in enumerate(top, 1)]
        return hits, len(candidates)

    def save(self, folder: Path) -> None:
        data = array('f', [x for c in self.centroids for x in c])
        if sys.byteorder != 'little':
            data.byteswap()
        (folder / 'ivf-centroids.f32').write_bytes(data.tobytes())
        record = {'format_version': FORMAT_VERSION,
                  'model_digest': self.base.record['model']['ollama_digest'],
                  'vectors_sha256': self.base.record['vectors_sha256'],
                  'centroids_sha256': hashlib.sha256(data.tobytes()).hexdigest(),
                  **self.settings, 'list_sizes': [len(l) for l in self.lists], 'lists': self.lists}
        (folder / 'ivf.json').write_text(json.dumps(record, indent=1) + '\n')

    @classmethod
    def load(cls, base: VectorIndex, folder: Path = HERE) -> 'IVFIndex':
        record = json.loads((folder / 'ivf.json').read_text())
        if record.get('format_version') != FORMAT_VERSION:
            raise SearchError(f"ivf.json format {record.get('format_version')}; this code reads {FORMAT_VERSION}")
        if record['model_digest'] != base.record['model']['ollama_digest'] \
                or record['vectors_sha256'] != base.record['vectors_sha256']:
            raise SearchError('the IVF index was built from different vectors; build it again')
        raw = (folder / 'ivf-centroids.f32').read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['centroids_sha256']:
            raise SearchError('ivf-centroids.f32 does not match ivf.json')
        lists = record['lists']
        if sorted(i for l in lists for i in l) != list(range(len(base.vectors))) or len(lists) != record['nlist']:
            raise SearchError('the lists must contain every stored vector exactly once')
        data = array('f')
        data.frombytes(raw)
        if sys.byteorder != 'little':
            data.byteswap()
        d = base.dimensions
        centroids = [data[i:i + d].tolist() for i in range(0, len(data), d)]
        settings = {key: record[key] for key in ('nlist', 'seed', 'max_iterations', 'iterations', 'converged')}
        return cls(base, centroids, lists, settings)


if __name__ == '__main__':
    # python ivf.py build 16          build and save the index with 16 lists
    # python ivf.py "question" 2      search with 2 probes (needs Ollama)
    if sys.argv[1] == 'build':
        index = IVFIndex.build(VectorIndex(), int(sys.argv[2]))
        index.save(HERE)
        print(json.dumps({key: value for key, value in index.settings.items()}))
    else:
        from embedder import MANIFEST, Embedder
        index = IVFIndex.load(VectorIndex())
        hits, scored = index.search(Embedder().query(sys.argv[1]), MANIFEST['ollama_digest'],
                                    nprobe=int(sys.argv[2]) if len(sys.argv) > 2 else 1)
        print(f'scored {scored} of {len(index.base.vectors)} vectors')
        for hit in hits:
            print(f"{hit['rank']}. {hit['score']:.4f}  {hit['id']}")
