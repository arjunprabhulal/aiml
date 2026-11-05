"""Memory service, version 4: attributes, authority and resolutions.

Standard library only. Extends the version 3 store (kinds, provenance,
corrections, expiry, deletion). A fact may name the attribute it describes
and whether the user stated it or a model inferred it. A resolution retires a
memory without deleting it. Opening a version 1 to 3 file migrates it to
version 4 in one transaction.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import re
import sqlite3

SCHEMA_VERSION = 4
AUTHORITIES = ('user', 'inferred')
KINDS = ('working', 'semantic', 'episodic')
V1_SCHEMA = """
CREATE TABLE memories (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    task_id TEXT,
    text TEXT NOT NULL CHECK (length(trim(text)) > 0),
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX memories_by_scope ON memories (user_id, task_id);
"""
# Each step moves the file one version forward. All steps run in one transaction.
STEPS = {
    0: [statement for statement in V1_SCHEMA.split(';') if statement.strip()],
    1: [
        """CREATE TABLE memories_v2 (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            task_id TEXT,
            text TEXT NOT NULL CHECK (length(trim(text)) > 0),
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            supersedes INTEGER UNIQUE REFERENCES memories_v2 (id)
        )""",
        """CREATE TABLE deletions (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            memory_ids TEXT NOT NULL,
            reason TEXT NOT NULL,
            deleted_at TEXT NOT NULL
        )""",
        'INSERT INTO memories_v2 (id, user_id, task_id, text, source, created_at) '
        'SELECT id, user_id, task_id, text, source, created_at FROM memories',
        'DROP TABLE memories',
        'ALTER TABLE memories_v2 RENAME TO memories',
        'CREATE INDEX memories_by_scope ON memories (user_id, task_id)',
    ],
    2: [
        """CREATE TABLE memories_v3 (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            task_id TEXT,
            kind TEXT NOT NULL DEFAULT 'semantic' CHECK (kind IN ('working', 'semantic', 'episodic')),
            text TEXT NOT NULL CHECK (length(trim(text)) > 0),
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            occurred_at TEXT,
            expires_at TEXT,
            supersedes INTEGER UNIQUE REFERENCES memories_v3 (id),
            CHECK ((kind = 'episodic') = (occurred_at IS NOT NULL)),
            CHECK (kind != 'working' OR task_id IS NOT NULL)
        )""",
        'INSERT INTO memories_v3 (id, user_id, task_id, text, source, created_at, expires_at, supersedes) '
        'SELECT id, user_id, task_id, text, source, created_at, expires_at, supersedes FROM memories',
        'DROP TABLE memories',
        'ALTER TABLE memories_v3 RENAME TO memories',
        'CREATE INDEX memories_by_scope ON memories (user_id, task_id)',
    ],
    3: [
        """CREATE TABLE memories_v4 (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            task_id TEXT,
            kind TEXT NOT NULL DEFAULT 'semantic' CHECK (kind IN ('working', 'semantic', 'episodic')),
            attribute TEXT CHECK (attribute IS NULL OR kind = 'semantic'),
            authority TEXT NOT NULL DEFAULT 'user' CHECK (authority IN ('user', 'inferred')),
            text TEXT NOT NULL CHECK (length(trim(text)) > 0),
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            occurred_at TEXT,
            expires_at TEXT,
            supersedes INTEGER UNIQUE REFERENCES memories_v4 (id),
            CHECK ((kind = 'episodic') = (occurred_at IS NOT NULL)),
            CHECK (kind != 'working' OR task_id IS NOT NULL)
        )""",
        'INSERT INTO memories_v4 (id, user_id, task_id, kind, text, source, created_at, occurred_at, expires_at, '
        'supersedes) SELECT id, user_id, task_id, kind, text, source, created_at, occurred_at, expires_at, '
        'supersedes FROM memories',
        'DROP TABLE memories',
        'ALTER TABLE memories_v4 RENAME TO memories',
        'CREATE INDEX memories_by_scope ON memories (user_id, task_id)',
        """CREATE TABLE resolutions (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            kept_id INTEGER NOT NULL REFERENCES memories (id),
            retired_id INTEGER NOT NULL UNIQUE REFERENCES memories (id),
            rule TEXT NOT NULL,
            resolved_at TEXT NOT NULL
        )""",
    ],
}
EXPECTED_TABLES = {1: {'memories'}, 2: {'memories', 'deletions'}, 3: {'memories', 'deletions'}}
IDENTIFIER = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
MAX_TEXT = 2_000
WORD = re.compile(r'[a-z0-9]+')
STOPWORDS = frozenset('a an and are as at be by did do does for from how i in is it my of on or that the this '
                      'to was we what when where which who will with you your'.split())


class MemoryInputError(ValueError):
    """Invalid scope, text, source or setting; nothing was written."""


class MemoryNotFound(LookupError):
    """No such memory in this scope. The same error covers another user's memory."""


class SchemaError(RuntimeError):
    """The database file has a schema this code does not understand."""


def _identifier(value, where):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise MemoryInputError(f'{where} must match {IDENTIFIER.pattern}')
    return value


@dataclass(frozen=True)
class Scope:
    user: str
    task: str

    def __post_init__(self):
        _identifier(self.user, 'scope.user')
        _identifier(self.task, 'scope.task')


class Clock:
    """A deterministic clock: each reading is one minute later; advance() jumps ahead."""

    def __init__(self, start: str = '2026-10-20T09:00:00+00:00'):
        self.moment = datetime.fromisoformat(start)

    def now(self) -> str:
        value = self.moment
        self.moment += timedelta(minutes=1)
        return value.isoformat()

    def peek(self) -> str:
        return self.moment.isoformat()

    def advance(self, **delta):
        self.moment += timedelta(**delta)


def words(text: str) -> set[str]:
    return set(WORD.findall(text.lower())) - STOPWORDS


def _text(value, where):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise MemoryInputError(f'{where} must be nonblank and at most {MAX_TEXT} characters')
    return value


class MemoryStore:
    def __init__(self, path: str, clock: Clock, secure_delete: bool = True):
        self.clock = clock
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys = ON')
        # Overwrite deleted rows with zeros so forgotten text does not stay in the file.
        self.db.execute(f'PRAGMA secure_delete = {"ON" if secure_delete else "OFF"}')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if (version == 0 and not tables) or (version in EXPECTED_TABLES and tables == EXPECTED_TABLES[version]):
            self._migrate(version)
        elif version != SCHEMA_VERSION:
            self.db.close()
            raise SchemaError(f'database schema version {version}; this code reads versions 1 to {SCHEMA_VERSION}')

    def _migrate(self, version: int):
        """Run every step from `version` to the current version in one transaction."""
        try:
            self.db.execute('BEGIN')
            for step in range(version, SCHEMA_VERSION):
                for statement in STEPS[step]:
                    self.db.execute(statement)
            self.db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
            self.db.commit()
        except BaseException:
            self.db.rollback()
            self.db.close()
            raise

    def close(self):
        self.db.close()

    # Every read of memories goes through this scoped query.
    def _rows(self, scope: Scope) -> list[dict]:
        cursor = self.db.execute(
            'SELECT id, task_id, kind, attribute, authority, text, source, created_at, occurred_at, expires_at, '
            'supersedes, '
            '(SELECT newer.id FROM memories AS newer WHERE newer.supersedes = memories.id) AS superseded_by, '
            '(SELECT kept_id FROM resolutions WHERE retired_id = memories.id) AS retired_by '
            'FROM memories WHERE user_id = ? AND (task_id IS NULL OR task_id = ?) ORDER BY id',
            (scope.user, scope.task))
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def _find(self, scope: Scope, memory_id: int) -> tuple[dict, dict]:
        rows = {row['id']: row for row in self._rows(scope)}
        if memory_id not in rows:
            raise MemoryNotFound(f'no memory {memory_id} in this scope')
        return rows[memory_id], rows

    def _expiry(self, created: str, ttl_days: int | None) -> str | None:
        if ttl_days is None:
            return None
        if type(ttl_days) is not int or not 1 <= ttl_days <= 3650:
            raise MemoryInputError('ttl_days must be an integer from 1 to 3650')
        return (datetime.fromisoformat(created) + timedelta(days=ttl_days)).isoformat()

    def remember(self, scope: Scope, level: str, text: str, source: str, ttl_days: int | None = None,
                 kind: str = 'semantic', occurred_at: str | None = None, attribute: str | None = None,
                 authority: str = 'user') -> int:
        if level not in ('user', 'task'):
            raise MemoryInputError('level must be user or task')
        if authority not in AUTHORITIES:
            raise MemoryInputError(f'authority must be one of {AUTHORITIES}')
        if attribute is not None:
            if kind != 'semantic':
                raise MemoryInputError('only a semantic memory names an attribute')
            _identifier(attribute, 'attribute')
        if kind not in KINDS:
            raise MemoryInputError(f'kind must be one of {KINDS}')
        if kind == 'working' and level != 'task':
            raise MemoryInputError('working memory belongs to one task')
        if (kind == 'episodic') != (occurred_at is not None):
            raise MemoryInputError('an episode needs occurred_at, and only an episode has one')
        if occurred_at is not None:
            # Plain dates only, so stored values sort correctly as text.
            try:
                if len(occurred_at) != 10:
                    raise ValueError
                date.fromisoformat(occurred_at)
            except (TypeError, ValueError):
                raise MemoryInputError('occurred_at must be a date in YYYY-MM-DD form') from None
        _text(text, 'memory text')
        _text(source, 'source')
        self._expiry(self.clock.peek(), ttl_days)  # validate before reading the clock
        created = self.clock.now()
        with self.db:
            cursor = self.db.execute(
                'INSERT INTO memories (user_id, task_id, kind, attribute, authority, text, source, created_at, '
                'occurred_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (scope.user, scope.task if level == 'task' else None, kind, attribute, authority, text, source,
                 created, occurred_at, self._expiry(created, ttl_days)))
        return cursor.lastrowid

    def correct(self, scope: Scope, memory_id: int, text: str, source: str, ttl_days: int | None = None) -> int:
        """Store a corrected memory that supersedes the current one. The old version stays as history."""
        old, _ = self._find(scope, memory_id)
        if old['superseded_by'] is not None:
            raise MemoryInputError(f'memory {memory_id} was already corrected by {old["superseded_by"]}; correct the newest')
        _text(text, 'memory text')
        _text(source, 'source')
        self._expiry(self.clock.peek(), ttl_days)
        created = self.clock.now()
        with self.db:
            cursor = self.db.execute(
                'INSERT INTO memories (user_id, task_id, kind, attribute, authority, text, source, created_at, '
                'occurred_at, expires_at, supersedes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (scope.user, old['task_id'], old['kind'], old['attribute'], 'user', text, source, created,
                 old['occurred_at'], self._expiry(created, ttl_days), memory_id))
        return cursor.lastrowid

    def history(self, scope: Scope, memory_id: int) -> list[dict]:
        """Every version of a memory, oldest first, with its source."""
        _, rows = self._find(scope, memory_id)
        chain = [rows[memory_id]]
        while chain[0]['supersedes'] is not None:
            chain.insert(0, rows[chain[0]['supersedes']])
        while chain[-1]['superseded_by'] is not None:
            chain.append(rows[chain[-1]['superseded_by']])
        return [{key: row[key] for key in ('id', 'text', 'source', 'created_at', 'supersedes')} for row in chain]

    def _closure(self, user: str, ids: list[int]) -> list[int]:
        """Every version of these memories and every memory retired in their favor, recursively.

        Deleting a kept memory without the memories it retired would make them current again.
        """
        found, pending = set(), list(ids)
        while pending:
            memory_id = pending.pop()
            if memory_id in found:
                continue
            found.add(memory_id)
            row = self.db.execute('SELECT supersedes FROM memories WHERE id = ? AND user_id = ?',
                                  (memory_id, user)).fetchone()
            if row and row[0] is not None:
                pending.append(row[0])
            pending += [r[0] for r in self.db.execute(
                'SELECT id FROM memories WHERE supersedes = ? AND user_id = ?', (memory_id, user))]
            pending += [r[0] for r in self.db.execute(
                'SELECT retired_id FROM resolutions WHERE kept_id = ? AND user_id = ?', (memory_id, user))]
        return sorted(found)

    def _delete(self, user: str, ids: list[int], reason: str, at: str):
        marks = ', '.join('?' * len(ids))
        self.db.execute(f'DELETE FROM resolutions WHERE user_id = ? AND (kept_id IN ({marks}) OR retired_id IN ({marks}))',
                        (user, *ids, *ids))
        for deleted in sorted(ids, reverse=True):  # newest first: no remaining row refers to a deleted one
            self.db.execute('DELETE FROM memories WHERE id = ? AND user_id = ?', (deleted, user))
        self.db.execute('INSERT INTO deletions (user_id, memory_ids, reason, deleted_at) VALUES (?, ?, ?, ?)',
                        (user, json.dumps(ids), reason, at))

    def forget(self, scope: Scope, memory_id: int, reason: str) -> list[int]:
        """Delete every version of a memory, and the memories it retired; record IDs, not text."""
        _text(reason, 'reason')
        ids = self._closure(scope.user, [row['id'] for row in self.history(scope, memory_id)])
        with self.db:
            self._delete(scope.user, ids, reason, self.clock.now())
        marks = ', '.join('?' * len(ids))
        if self.db.execute(f'SELECT count(*) FROM memories WHERE id IN ({marks})', ids).fetchone()[0]:
            raise RuntimeError('a deleted memory is still stored')
        return ids

    def purge_expired(self) -> int:
        """Delete each memory whose newest version has expired, with its versions and the memories it retired."""
        now = self.clock.peek()
        expired = self.db.execute(
            'SELECT user_id, id FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ? '
            'AND NOT EXISTS (SELECT 1 FROM memories AS newer WHERE newer.supersedes = memories.id) ORDER BY id',
            (now,)).fetchall()
        removed = set()
        with self.db:
            for user, newest in expired:
                if newest in removed:
                    continue
                ids = self._closure(user, [newest])
                self._delete(user, ids, 'expired', now)
                removed.update(ids)
        return len(removed)

    def current(self, scope: Scope, shadow: bool = True) -> list[dict]:
        """Visible memories that are not superseded, retired or expired, oldest first.

        A task-level fact about an attribute overrides user-level facts about the
        same attribute inside that task only.
        """
        now = self.clock.peek()
        rows = [row for row in self._rows(scope)
                if row['superseded_by'] is None and row['retired_by'] is None
                and not (row['expires_at'] and row['expires_at'] <= now)]
        if not shadow:
            return rows
        task_attributes = {row['attribute'] for row in rows if row['task_id'] and row['attribute']}
        return [row for row in rows if row['task_id'] or row['attribute'] not in task_attributes]

    def resolve(self, scope: Scope, decisions: list[tuple[int, int, str]]) -> None:
        """Retire memories in favor of others, all in one transaction. Retired memories stay stored."""
        rows = {row['id']: row for row in self.current(scope, shadow=False)}
        for kept, retired, rule in decisions:
            if kept not in rows or retired not in rows or kept == retired:
                raise MemoryNotFound(f'no current memories {kept} and {retired} in this scope')
            if rows[kept]['task_id'] != rows[retired]['task_id']:
                raise MemoryInputError('only memories at the same level and task can be resolved')
            _text(rule, 'rule')
        at = self.clock.now()
        with self.db:
            for kept, retired, rule in decisions:
                self.db.execute('INSERT INTO resolutions (user_id, kept_id, retired_id, rule, resolved_at) '
                                'VALUES (?, ?, ?, ?, ?)', (scope.user, kept, retired, rule, at))

    def recall(self, scope: Scope, query: str, limit: int = 3) -> list[dict]:
        """Current memories only: not superseded and not expired at the current time."""
        if type(limit) is not int or not 1 <= limit <= 20:
            raise MemoryInputError('limit must be an integer from 1 to 20')
        wanted = words(query)
        scored = []
        for row in self.current(scope):
            score = len(wanted & words(row['text']))
            if score:
                scored.append({'id': row['id'], 'kind': row['kind'], 'level': 'task' if row['task_id'] else 'user',
                               'text': row['text'],
                               'source': row['source'], 'supersedes': row['supersedes'],
                               'expires_at': row['expires_at'], 'score': score})
        scored.sort(key=lambda m: (-m['score'], -m['id']))
        return scored[:limit]

    def resolutions(self, scope: Scope) -> list[dict]:
        cursor = self.db.execute('SELECT kept_id, retired_id, rule, resolved_at FROM resolutions '
                                 'WHERE user_id = ? ORDER BY id', (scope.user,))
        return [{'kept': kept, 'retired': retired, 'rule': rule, 'resolved_at': at} for kept, retired, rule, at in cursor]

    def deletions(self, scope: Scope) -> list[dict]:
        cursor = self.db.execute('SELECT memory_ids, reason, deleted_at FROM deletions WHERE user_id = ? ORDER BY id',
                                 (scope.user,))
        return [{'memory_ids': json.loads(ids), 'reason': reason, 'deleted_at': at} for ids, reason, at in cursor]
