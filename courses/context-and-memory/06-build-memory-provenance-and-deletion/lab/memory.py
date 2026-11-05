"""Memory service, version 2: provenance, corrections, expiry and deletion.

Standard library only. Extends the version 1 store from the memory service
build. A correction adds a new memory that supersedes the old one; recall
returns only current, unexpired memories; forget deletes every version of a
memory and records the deletion without its text.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import sqlite3

SCHEMA_VERSION = 2
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
V2_TABLES = [
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
]
V2_FINISH = [
    'ALTER TABLE memories_v2 RENAME TO memories',
    'CREATE INDEX memories_by_scope ON memories (user_id, task_id)',
    f'PRAGMA user_version = {SCHEMA_VERSION}',
]
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
        if version == 0 and not tables:
            self._migrate(create_v1=True)
        elif version == 1 and tables == {'memories'}:
            self._migrate(create_v1=False)
        elif version != SCHEMA_VERSION:
            self.db.close()
            raise SchemaError(f'database schema version {version}; this code reads versions 1 and {SCHEMA_VERSION}')

    def _migrate(self, create_v1: bool):
        """Move a new or version 1 file to version 2 in one transaction."""
        try:
            self.db.execute('BEGIN')
            if create_v1:
                for statement in filter(str.strip, V1_SCHEMA.split(';')):
                    self.db.execute(statement)
            for statement in V2_TABLES:
                self.db.execute(statement)
            self.db.execute('INSERT INTO memories_v2 (id, user_id, task_id, text, source, created_at) '
                            'SELECT id, user_id, task_id, text, source, created_at FROM memories')
            self.db.execute('DROP TABLE memories')
            for statement in V2_FINISH:
                self.db.execute(statement)
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
            'SELECT id, task_id, text, source, created_at, expires_at, supersedes, '
            '(SELECT newer.id FROM memories AS newer WHERE newer.supersedes = memories.id) AS superseded_by '
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

    def remember(self, scope: Scope, level: str, text: str, source: str, ttl_days: int | None = None) -> int:
        if level not in ('user', 'task'):
            raise MemoryInputError('level must be user or task')
        _text(text, 'memory text')
        _text(source, 'source')
        self._expiry(self.clock.peek(), ttl_days)  # validate before reading the clock
        created = self.clock.now()
        with self.db:
            cursor = self.db.execute(
                'INSERT INTO memories (user_id, task_id, text, source, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)',
                (scope.user, scope.task if level == 'task' else None, text, source, created,
                 self._expiry(created, ttl_days)))
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
                'INSERT INTO memories (user_id, task_id, text, source, created_at, expires_at, supersedes) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (scope.user, old['task_id'], text, source, created, self._expiry(created, ttl_days), memory_id))
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

    def forget(self, scope: Scope, memory_id: int, reason: str) -> list[int]:
        """Delete every version of a memory and record which IDs were deleted, without text."""
        _text(reason, 'reason')
        ids = [row['id'] for row in self.history(scope, memory_id)]
        marks = ', '.join('?' * len(ids))
        with self.db:
            # Newest first, so no remaining row refers to a deleted one.
            for deleted in reversed(ids):
                self.db.execute('DELETE FROM memories WHERE id = ? AND user_id = ?', (deleted, scope.user))
            self.db.execute('INSERT INTO deletions (user_id, memory_ids, reason, deleted_at) VALUES (?, ?, ?, ?)',
                            (scope.user, json.dumps(ids), reason, self.clock.now()))
        if self.db.execute(f'SELECT count(*) FROM memories WHERE id IN ({marks})', ids).fetchone()[0]:
            raise RuntimeError('a deleted memory is still stored')
        return ids

    def purge_expired(self) -> int:
        """Delete every version of each memory whose newest version has expired, for every user.

        Deleting only the expired newest version would make the older version
        it corrected current again. Run this as a scheduled job.
        """
        now = self.clock.peek()
        expired = self.db.execute(
            'SELECT user_id, id FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ? '
            'AND NOT EXISTS (SELECT 1 FROM memories AS newer WHERE newer.supersedes = memories.id) ORDER BY id',
            (now,)).fetchall()
        removed = 0
        with self.db:
            for user, newest in expired:
                chain = [newest]
                while (older := self.db.execute('SELECT supersedes FROM memories WHERE id = ? AND user_id = ?',
                                                (chain[-1], user)).fetchone()[0]) is not None:
                    chain.append(older)
                for memory_id in chain:  # newest first
                    self.db.execute('DELETE FROM memories WHERE id = ? AND user_id = ?', (memory_id, user))
                self.db.execute('INSERT INTO deletions (user_id, memory_ids, reason, deleted_at) VALUES (?, ?, ?, ?)',
                                (user, json.dumps(sorted(chain)), 'expired', now))
                removed += len(chain)
        return removed

    def recall(self, scope: Scope, query: str, limit: int = 3) -> list[dict]:
        """Current memories only: not superseded and not expired at the current time."""
        if type(limit) is not int or not 1 <= limit <= 20:
            raise MemoryInputError('limit must be an integer from 1 to 20')
        now = self.clock.peek()
        wanted = words(query)
        scored = []
        for row in self._rows(scope):
            if row['superseded_by'] is not None or (row['expires_at'] and row['expires_at'] <= now):
                continue
            score = len(wanted & words(row['text']))
            if score:
                scored.append({'id': row['id'], 'level': 'task' if row['task_id'] else 'user', 'text': row['text'],
                               'source': row['source'], 'supersedes': row['supersedes'],
                               'expires_at': row['expires_at'], 'score': score})
        scored.sort(key=lambda m: (-m['score'], -m['id']))
        return scored[:limit]

    def deletions(self, scope: Scope) -> list[dict]:
        cursor = self.db.execute('SELECT memory_ids, reason, deleted_at FROM deletions WHERE user_id = ? ORDER BY id',
                                 (scope.user,))
        return [{'memory_ids': json.loads(ids), 'reason': reason, 'deleted_at': at} for ids, reason, at in cursor]
