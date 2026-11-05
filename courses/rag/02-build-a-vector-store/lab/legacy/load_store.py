"""Load the embedding build's vectors and the lesson metadata into store.sqlite.

    python load_store.py            # writes store.sqlite next to this file

The source files are checked against the hashes in index.json first, so a
store is never built from a corpus or vector file that changed after
embedding. The load is one transaction.
"""
import hashlib
import json
from pathlib import Path
import sys
from store import StoreError, VectorStore, from_bytes

HERE = Path(__file__).parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(path: Path, folder: Path = HERE) -> VectorStore:
    index = json.loads((folder / 'index.json').read_text())
    for name, key in (('corpus.json', 'corpus_sha256'), ('vectors.f32', 'vectors_sha256')):
        if sha256(folder / name) != index[key]:
            raise StoreError(f'{name} does not match index.json; embed it again')
    passages = json.loads((folder / 'corpus.json').read_text())['passages']
    lessons = json.loads((folder / 'lesson-metadata.json').read_text())['lessons']
    missing = sorted({p['lesson'] for p in passages} - set(lessons))
    if missing:
        raise StoreError(f'no metadata for lessons {missing}')
    d = index['model']['dimensions']
    flat = from_bytes((folder / 'vectors.f32').read_bytes())
    vectors = [flat[i:i + d].tolist() for i in range(0, len(flat), d)]
    rows = [{**p, **lessons[p['lesson']]} for p in passages]
    store = VectorStore.create(path, index['model']['ollama_digest'], d)
    try:
        store.add(rows, vectors, index['model']['ollama_digest'])
    except StoreError:
        store.close()
        Path(path).unlink()  # remove the empty store this call created
        raise
    return store


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'store.sqlite'
    store = build(target)
    print(f'{store.count()} passages in {target}')
