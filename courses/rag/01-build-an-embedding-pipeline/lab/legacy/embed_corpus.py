"""Embed every corpus passage and write vectors.f32 plus index.json.

vectors.f32 holds one little-endian float32 row per passage, in corpus order.
index.json records which model, digest and corpus produced them, the token
count of every passage, and SHA-256 hashes, so a reader can tell when the
vectors no longer match the corpus or the model.
"""
from array import array
import hashlib
import json
from pathlib import Path
import sys
import time
from embedder import MANIFEST, Embedder

HERE = Path(__file__).parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_vectors(path: Path, vectors: list[list[float]]):
    rows = array('f', [x for vector in vectors for x in vector])
    if sys.byteorder != 'little':
        rows.byteswap()
    path.write_bytes(rows.tobytes())


def read_vectors(path: Path, dimensions: int) -> list[list[float]]:
    rows = array('f')
    rows.frombytes(path.read_bytes())
    if sys.byteorder != 'little':
        rows.byteswap()
    if len(rows) % dimensions:
        raise ValueError(f'{path.name} does not hold whole {dimensions}-dimensional rows')
    return [rows[i:i + dimensions].tolist() for i in range(0, len(rows), dimensions)]


def main():
    corpus = json.loads((HERE / 'corpus.json').read_text())
    passages = corpus['passages']
    embedder = Embedder()
    started = time.perf_counter()
    vectors, tokens = embedder.documents([p['text'] for p in passages], batch_size=1)
    seconds = time.perf_counter() - started
    write_vectors(HERE / 'vectors.f32', vectors)
    index = {
        'model': {key: MANIFEST[key] for key in ('publisher_model', 'publisher_revision', 'ollama_tag',
                                                 'ollama_digest', 'dimensions', 'license')},
        'document_instruction': MANIFEST['document_instruction'],
        'corpus_sha256': sha256(HERE / 'corpus.json'),
        'vectors_sha256': sha256(HERE / 'vectors.f32'),
        'count': len(passages),
        'ids': [p['id'] for p in passages],
        'tokens': tokens,
    }
    (HERE / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
    print(json.dumps({'passages': len(passages), 'tokens': sum(tokens), 'seconds': round(seconds, 1)}))


if __name__ == '__main__':
    main()
