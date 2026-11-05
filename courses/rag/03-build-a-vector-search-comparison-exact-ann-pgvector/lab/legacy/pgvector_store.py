"""Store and search the passages in PostgreSQL with the pgvector extension.

Works with a DB-API 2.0 connection that uses the 'format' parameter style
(%s), such as pg8000. Every value goes to the server as a parameter. Query
settings and index options are numbers or words checked against an allow
list, because PostgreSQL's SET and WITH clauses do not take parameters.

Vectors travel in pgvector's text form, '[0.1,0.2,...]'. A float32 value
written with repr() reads back as the same float32, so stored vectors equal
the source file bit for bit; compare.py checks this after loading.
"""
import math
import re

FIELDS = ('lesson', 'kind', 'topic')
SETTINGS = {
    'ivfflat.probes': int,
    'hnsw.ef_search': int,
    'hnsw.iterative_scan': ('off', 'strict_order', 'relaxed_order'),
    'enable_seqscan': ('on', 'off'),
}
INDEX_OPTIONS = {'ivfflat': {'lists': int}, 'hnsw': {'m': int, 'ef_construction': int}}
NAME = re.compile(r'[a-z_][a-z0-9_]{0,62}')


class PgvectorError(Exception):
    pass


def vector_text(vector: list[float]) -> str:
    if not vector or not all(math.isfinite(x) for x in vector):
        raise PgvectorError('vector must be non-empty and finite')
    return '[' + ','.join(repr(float(x)) for x in vector) + ']'


def parse_vector(text: str) -> list[float]:
    return [float(x) for x in text.strip('[]').split(',')]


def where_sql(where: dict | None) -> tuple[str, list]:
    """{'kind': 'build'} becomes 'kind = %s' with ['build']; only FIELDS may be filtered."""
    parts, params = [], []
    for field, value in (where or {}).items():
        if field not in FIELDS:
            raise PgvectorError(f'unknown filter field {field!r}; use one of {FIELDS}')
        if type(value) is not str:
            raise PgvectorError(f'{field!r} filter value must be text')
        parts.append(f'{field} = %s')
        params.append(value)
    return ' AND '.join(parts) or 'true', params


def setting_sql(name: str, value) -> str:
    if name not in SETTINGS:
        raise PgvectorError(f'setting {name!r} is not allowed; use one of {sorted(SETTINGS)}')
    allowed = SETTINGS[name]
    if allowed is int:
        if type(value) is not int or value < 1:
            raise PgvectorError(f'{name} must be a positive integer')
    elif value not in allowed:
        raise PgvectorError(f'{name} must be one of {allowed}')
    return f'SET LOCAL {name} = {value}'


class PgvectorStore:
    def __init__(self, conn, schema: str):
        if not NAME.fullmatch(schema):
            raise PgvectorError(f'schema name {schema!r} must match {NAME.pattern}')
        self.conn, self.schema = conn, schema
        rows = self.fetch(f'SELECT key, value FROM {schema}.meta', [])
        meta = dict(rows)
        self.model_digest, self.dimensions = meta['model_digest'], int(meta['dimensions'])

    @classmethod
    def create(cls, conn, schema: str, model_digest: str, dimensions: int) -> 'PgvectorStore':
        if not NAME.fullmatch(schema):
            raise PgvectorError(f'schema name {schema!r} must match {NAME.pattern}')
        if type(dimensions) is not int or dimensions < 1:
            raise PgvectorError('dimensions must be a positive integer')
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM information_schema.schemata WHERE schema_name = %s', [schema])
        if cursor.fetchall():
            conn.rollback()
            raise PgvectorError(f'schema {schema} already exists; drop it or choose another name')
        try:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS vector')
            cursor.execute(f'CREATE SCHEMA {schema}')
            cursor.execute(f'CREATE TABLE {schema}.meta (key text PRIMARY KEY, value text NOT NULL)')
            cursor.execute(f"""CREATE TABLE {schema}.passages (
                row integer PRIMARY KEY,
                id text NOT NULL UNIQUE,
                lesson text NOT NULL,
                kind text NOT NULL,
                topic text NOT NULL,
                embedding vector({dimensions}) NOT NULL)""")
            for field in ('kind', 'topic'):
                cursor.execute(f'CREATE INDEX passages_{field} ON {schema}.passages ({field})')
            cursor.executemany(f'INSERT INTO {schema}.meta VALUES (%s, %s)',
                               [('model_digest', model_digest), ('dimensions', str(dimensions))])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return cls(conn, schema)

    def fetch(self, sql: str, params: list) -> list:
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            self.conn.commit()
            return rows
        except Exception:
            self.conn.rollback()
            raise

    def add(self, passages: list[dict], vectors: list[list[float]], model_digest: str) -> None:
        """Insert all rows in one transaction."""
        if model_digest != self.model_digest:
            raise PgvectorError('vectors come from a different model build than the store')
        if len(passages) != len(vectors) or any(len(v) != self.dimensions for v in vectors):
            raise PgvectorError(f'need one {self.dimensions}-dimension vector per passage')
        rows = [(i, p['id'], p['lesson'], p['kind'], p['topic'], vector_text(v))
                for i, (p, v) in enumerate(zip(passages, vectors))]
        cursor = self.conn.cursor()
        try:
            cursor.executemany(f'INSERT INTO {self.schema}.passages VALUES (%s, %s, %s, %s, %s, %s::vector)', rows)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def create_index(self, method: str, **options) -> None:
        """Replace the vector index with an ivfflat or hnsw index for cosine distance."""
        if method not in INDEX_OPTIONS:
            raise PgvectorError(f'index method must be one of {sorted(INDEX_OPTIONS)}')
        for name, value in options.items():
            if name not in INDEX_OPTIONS[method] or type(value) is not int or value < 1:
                raise PgvectorError(f'{method} option {name}={value!r} is not allowed')
        with_clause = f" WITH ({', '.join(f'{k} = {v}' for k, v in options.items())})" if options else ''
        cursor = self.conn.cursor()
        try:
            cursor.execute(f'DROP INDEX IF EXISTS {self.schema}.passages_embedding')
            cursor.execute(f'CREATE INDEX passages_embedding ON {self.schema}.passages '
                           f'USING {method} (embedding vector_cosine_ops){with_clause}')
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def drop_metadata_indexes(self) -> None:
        """Drop the B-tree indexes on kind and topic, leaving the vector index as the only index."""
        cursor = self.conn.cursor()
        for field in ('kind', 'topic'):
            cursor.execute(f'DROP INDEX IF EXISTS {self.schema}.passages_{field}')
        self.conn.commit()

    def drop_index(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(f'DROP INDEX IF EXISTS {self.schema}.passages_embedding')
        self.conn.commit()

    def sizes(self) -> dict:
        """Bytes on disk for the table without its indexes, and for the vector index."""
        rows = self.fetch("SELECT pg_table_size(%s::regclass), "
                          "coalesce(pg_relation_size(to_regclass(%s)), 0)",
                          [f'{self.schema}.passages', f'{self.schema}.passages_embedding'])
        return {'table_bytes': rows[0][0], 'vector_index_bytes': rows[0][1]}

    def query_sql(self, where: dict | None) -> tuple[str, list]:
        clause, params = where_sql(where)
        # Order by the distance alone: an index can only serve ORDER BY <distance> LIMIT k.
        sql = (f'SELECT id, lesson, 1 - (embedding <=> %s::vector) AS score FROM {self.schema}.passages '
               f'WHERE {clause} ORDER BY embedding <=> %s::vector LIMIT %s')
        return sql, params

    def search(self, query: list[float], model_digest: str, k: int = 5, where: dict | None = None,
               settings: dict | None = None, explain: bool = False) -> list:
        if model_digest != self.model_digest:
            raise PgvectorError('the query comes from a different model build than the store')
        if len(query) != self.dimensions:
            raise PgvectorError(f'query has {len(query)} dimensions; the store has {self.dimensions}')
        if type(k) is not int or k < 1:
            raise PgvectorError('k must be a positive integer')
        statements = [setting_sql(name, value) for name, value in (settings or {}).items()]
        sql, params = self.query_sql(where)
        text = vector_text(query)
        cursor = self.conn.cursor()
        try:
            for statement in statements:
                cursor.execute(statement)
            if explain:
                cursor.execute('EXPLAIN (FORMAT JSON) ' + sql, [text, *params, text, k])
                plan = cursor.fetchall()[0][0]
                self.conn.commit()
                return plan
            cursor.execute(sql, [text, *params, text, k])
            rows = cursor.fetchall()
            self.conn.commit()  # ends the transaction, so SET LOCAL settings end too
        except Exception:
            self.conn.rollback()
            raise
        return [{'id': pid, 'lesson': lesson, 'score': round(float(score), 6)} for pid, lesson, score in rows]
