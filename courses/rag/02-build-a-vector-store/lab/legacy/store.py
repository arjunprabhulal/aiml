"""A persistent vector store in one SQLite file, with metadata filters.

Each row holds one passage: its text, the metadata fields that filters may
use, and its vector as little-endian float32 bytes. The store records the
model digest and dimension that produced the vectors and refuses vectors
or queries from any other model build.

Search is exact: it scores every candidate row with the dot product, which
equals the cosine because stored vectors must have length 1.

    filtering='pre'   select the rows that match the filter, then score them
    filtering='post'  score every row, keep the best `candidates`, then
                      drop the rows that do not match the filter
"""
from array import array
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys

SCHEMA_VERSION = 1
UNIT_TOLERANCE = 1e-3
KINDS = ('foundation', 'build')
FIELDS = {'lesson': str, 'kind': str, 'topic': str, 'minutes': int}
OPERATORS = {'eq': '=', 'in': 'IN', 'gte': '>=', 'lte': '<='}


class StoreError(Exception):
    pass


def to_bytes(vector: list[float]) -> bytes:
    data = array('f', vector)
    if sys.byteorder != 'little':
        data.byteswap()
    return data.tobytes()


def from_bytes(blob: bytes) -> array:
    data = array('f')
    data.frombytes(blob)
    if sys.byteorder != 'little':
        data.byteswap()
    return data


def where_clause(where: dict | None) -> tuple[str, list]:
    """Turn {'topic': 'X', 'minutes': {'lte': 7}} into SQL and parameters.

    Field names come only from FIELDS and operators only from OPERATORS;
    every value is passed as a parameter, never inserted into the SQL text.
    """
    parts, params = [], []
    for field, condition in (where or {}).items():
        if field not in FIELDS:
            raise StoreError(f'unknown filter field {field!r}; use one of {sorted(FIELDS)}')
        if not isinstance(condition, dict):
            condition = {'eq': condition}
        if not condition:
            raise StoreError(f'empty condition for {field!r}')
        for op, value in condition.items():
            if op not in OPERATORS:
                raise StoreError(f'unknown operator {op!r}; use one of {sorted(OPERATORS)}')
            if op in ('gte', 'lte') and FIELDS[field] is not int:
                raise StoreError(f'{op!r} needs a numeric field, not {field!r}')
            values = value if op == 'in' else [value]
            if op == 'in' and (not isinstance(value, (list, tuple)) or not value):
                raise StoreError("'in' needs a non-empty list")
            for v in values:
                if type(v) is not FIELDS[field]:
                    raise StoreError(f'{field!r} values must be {FIELDS[field].__name__}, got {v!r}')
            marks = ', '.join('?' * len(values))
            parts.append(f'{field} IN ({marks})' if op == 'in' else f'{field} {OPERATORS[op]} ?')
            params += values
    return ' AND '.join(parts) or '1', params


class VectorStore:
    def __init__(self, path: Path, db: sqlite3.Connection):
        self.path, self.db = path, db
        meta = dict(db.execute('SELECT key, value FROM meta'))
        self.model_digest = meta['model_digest']
        self.dimensions = int(meta['dimensions'])

    @classmethod
    def create(cls, path: Path, model_digest: str, dimensions: int) -> 'VectorStore':
        path = Path(path)
        if path.exists():
            raise StoreError(f'{path} already exists; open it instead')
        if type(dimensions) is not int or dimensions < 1:
            raise StoreError('dimensions must be a positive integer')
        db = sqlite3.connect(path, isolation_level=None)
        with transaction(db):
            db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT')
            db.execute(f"""CREATE TABLE passages (
                row INTEGER PRIMARY KEY,
                id TEXT NOT NULL UNIQUE,
                lesson TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN {KINDS}),
                topic TEXT NOT NULL,
                minutes INTEGER NOT NULL CHECK (minutes > 0),
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                vector BLOB NOT NULL CHECK (length(vector) = {dimensions * 4})) STRICT""")
            db.execute('CREATE INDEX passages_topic ON passages (topic)')
            db.execute('CREATE INDEX passages_kind ON passages (kind)')
            db.executemany('INSERT INTO meta VALUES (?, ?)',
                           [('model_digest', model_digest), ('dimensions', str(dimensions))])
            db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        return cls(path, db)

    @classmethod
    def open(cls, path: Path) -> 'VectorStore':
        path = Path(path)
        if not path.is_file():
            raise StoreError(f'{path} does not exist')
        db = sqlite3.connect(f'file:{path}?mode=rw', uri=True, isolation_level=None)
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version != SCHEMA_VERSION:
                raise StoreError(f'schema version {version}; this code reads version {SCHEMA_VERSION}')
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise StoreError(f'{path} failed the SQLite integrity check')
            return cls(path, db)
        except (StoreError, sqlite3.DatabaseError) as error:
            db.close()
            raise StoreError(str(error)) from error

    def close(self) -> None:
        self.db.close()

    def check_vector(self, vector: list[float], unit: bool) -> None:
        if len(vector) != self.dimensions:
            raise StoreError(f'vector has {len(vector)} dimensions; the store has {self.dimensions}')
        if not all(math.isfinite(x) for x in vector):
            raise StoreError('vector must be finite')
        length = math.sqrt(sum(x * x for x in vector))
        if length == 0 or (unit and abs(length - 1) > UNIT_TOLERANCE):
            raise StoreError(f'vector length is {length:.6f}; stored vectors must have length 1')

    def add(self, passages: list[dict], vectors: list[list[float]], model_digest: str) -> int:
        """Add passages and their vectors in one transaction: all of them or none."""
        if model_digest != self.model_digest:
            raise StoreError('vectors come from a different model build than the store')
        if len(passages) != len(vectors) or not passages:
            raise StoreError('need one vector per passage and at least one passage')
        rows = []
        for p, vector in zip(passages, vectors):
            self.check_vector(vector, unit=True)
            if p.get('kind') not in KINDS or type(p.get('minutes')) is not int:
                raise StoreError(f"passage {p.get('id')!r} has invalid metadata")
            rows.append((p['id'], p['lesson'], p['kind'], p['topic'], p['minutes'], p['title'], p['text'],
                         to_bytes(vector)))
        try:
            with transaction(self.db):
                self.db.executemany('INSERT INTO passages (id, lesson, kind, topic, minutes, title, text, vector)'
                                    ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)', rows)
        except sqlite3.IntegrityError as error:
            raise StoreError(f'batch refused, nothing written: {error}') from error
        return len(rows)

    def count(self, where: dict | None = None) -> int:
        clause, params = where_clause(where)
        return self.db.execute(f'SELECT count(*) FROM passages WHERE {clause}', params).fetchone()[0]

    def vectors_sha256(self) -> str:
        """Hash of all vectors in insertion order: equals the source vectors.f32 hash after a load."""
        digest = hashlib.sha256()
        for (blob,) in self.db.execute('SELECT vector FROM passages ORDER BY row'):
            digest.update(blob)
        return digest.hexdigest()

    def search(self, query: list[float], model_digest: str, k: int = 5, where: dict | None = None,
               filtering: str = 'pre', candidates: int | None = None) -> list[dict]:
        if model_digest != self.model_digest:
            raise StoreError('the query comes from a different model build than the store')
        self.check_vector(query, unit=False)
        if type(k) is not int or k < 1:
            raise StoreError('k must be a positive integer')
        clause, params = where_clause(where)
        norm = math.sqrt(sum(x * x for x in query))
        q = [x / norm for x in query]

        def ranked(sql: str, args: list) -> list[tuple[float, int]]:
            scored = [(sum(a * b for a, b in zip(q, from_bytes(blob))), row)
                      for row, blob in self.db.execute(sql, args)]
            return sorted(scored, key=lambda s: (-s[0], s[1]))

        if filtering == 'pre':
            best = ranked(f'SELECT row, vector FROM passages WHERE {clause}', params)[:k]
        elif filtering == 'post':
            pool = candidates if candidates is not None else k
            if type(pool) is not int or pool < k:
                raise StoreError('candidates must be an integer of at least k')
            top = ranked('SELECT row, vector FROM passages', [])[:pool]
            rows = [row for _, row in top]
            keep = {r for (r,) in self.db.execute(
                f"SELECT row FROM passages WHERE row IN ({', '.join('?' * len(rows))}) AND {clause}",
                rows + params)}
            best = [s for s in top if s[1] in keep][:k]
        else:
            raise StoreError(f"filtering must be 'pre' or 'post', not {filtering!r}")
        hits = []
        for score, row in best:
            pid, lesson, kind, topic, minutes, title = self.db.execute(
                'SELECT id, lesson, kind, topic, minutes, title FROM passages WHERE row = ?', [row]).fetchone()
            hits.append({'id': pid, 'lesson': lesson, 'kind': kind, 'topic': topic, 'minutes': minutes,
                         'title': title, 'score': round(score, 6)})
        return hits


@contextmanager
def transaction(db: sqlite3.Connection):
    """BEGIN ... COMMIT, or ROLLBACK if anything inside raises."""
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
    except BaseException:
        db.execute('ROLLBACK')
        raise
    db.execute('COMMIT')


def main(argv: list[str]) -> None:
    """python store.py "question" [--kind build] [--topic "Search and retrieval"] [--max-minutes 10]"""
    from embedder import MANIFEST, Embedder
    args, where = argv[1:], {}
    question = args.pop(0)
    while args:
        flag, value = args.pop(0), args.pop(0)
        if flag == '--max-minutes':
            where['minutes'] = {'lte': int(value)}
        else:
            where[flag.removeprefix('--')] = value
    store = VectorStore.open(Path(__file__).with_name('store.sqlite'))
    vector = Embedder().query(question)
    for hit in store.search(vector, MANIFEST['ollama_digest'], k=5, where=where):
        print(f"{hit['score']:.3f}  {hit['kind']:<10} {hit['title']}")


if __name__ == '__main__':
    main(sys.argv)
