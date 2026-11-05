"""A persistent memory service with explicit user and task scope.

Standard library only: sqlite3 for storage. Every query that reads or writes
memories carries the user's ID; task memories also carry the task's ID. The
caller authenticates the user before it builds a Scope.
"""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import sqlite3

SCHEMA_VERSION = 1
SCHEMA = """
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
IDENTIFIER = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
MAX_TEXT = 2_000
WORD = re.compile(r'[a-z0-9]+')
STOPWORDS = frozenset('a an and are as at be by did do does for from how i in is it my of on or that the this '
                      'to was we what when where which who will with you your'.split())


class MemoryInputError(ValueError):
    """Invalid scope, memory text or source; nothing was written."""


class SchemaError(RuntimeError):
    """The database file has a schema this code does not understand."""


def _identifier(value, where):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise MemoryInputError(f'{where} must match {IDENTIFIER.pattern}')
    return value


@dataclass(frozen=True)
class Scope:
    """Who is asking: one authenticated user, working on one task."""
    user: str
    task: str

    def __post_init__(self):
        _identifier(self.user, 'scope.user')
        _identifier(self.task, 'scope.task')


def fixed_clock(start: str = '2026-10-20T09:00:00+00:00', step_seconds: int = 60) -> Callable[[], str]:
    """A deterministic clock for tests and demos: each call is one step later."""
    moment = datetime.fromisoformat(start)
    state = {'next': moment}

    def now() -> str:
        value = state['next']
        state['next'] = value + timedelta(seconds=step_seconds)
        return value.isoformat()
    return now


def system_clock() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def words(text: str) -> set[str]:
    return set(WORD.findall(text.lower())) - STOPWORDS


class MemoryStore:
    def __init__(self, path: str, clock: Callable[[], str] = system_clock):
        self.clock = clock
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys = ON')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        tables = self.db.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
        if version == 0 and tables == 0:
            # One explicit transaction: executescript() would commit on its own,
            # and the sqlite3 module opens no transaction before CREATE TABLE.
            try:
                self.db.execute('BEGIN')
                for statement in filter(str.strip, SCHEMA.split(';')):
                    self.db.execute(statement)
                self.db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
                self.db.commit()
            except BaseException:
                self.db.rollback()
                self.db.close()
                raise
        elif version != SCHEMA_VERSION:
            self.db.close()
            raise SchemaError(f'database schema version {version}; this code reads version {SCHEMA_VERSION}')

    def close(self):
        self.db.close()

    def remember(self, scope: Scope, level: str, text: str, source: str) -> int:
        """Store one memory at user level (every task) or task level (this task only)."""
        if level not in ('user', 'task'):
            raise MemoryInputError('level must be user or task')
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise MemoryInputError(f'memory text must be nonblank and at most {MAX_TEXT} characters')
        if not isinstance(source, str) or not source.strip():
            raise MemoryInputError('every memory needs a source')
        task = scope.task if level == 'task' else None
        with self.db:
            cursor = self.db.execute(
                'INSERT INTO memories (user_id, task_id, text, source, created_at) VALUES (?, ?, ?, ?, ?)',
                (scope.user, task, text, source, self.clock()))
        return cursor.lastrowid

    def _visible(self, scope: Scope) -> list[tuple]:
        # The only read path: this user's user-level memories and this task's memories.
        return self.db.execute(
            'SELECT id, task_id, text, source, created_at FROM memories '
            'WHERE user_id = ? AND (task_id IS NULL OR task_id = ?) ORDER BY id',
            (scope.user, scope.task)).fetchall()

    def recall(self, scope: Scope, query: str, limit: int = 3) -> list[dict]:
        """Return up to `limit` visible memories that share words with the query."""
        if type(limit) is not int or not 1 <= limit <= 20:
            raise MemoryInputError('limit must be an integer from 1 to 20')
        wanted = words(query)
        scored = []
        for memory_id, task, text, source, created in self._visible(scope):
            score = len(wanted & words(text))
            if score:
                scored.append({'id': memory_id, 'level': 'task' if task else 'user', 'text': text,
                               'source': source, 'created_at': created, 'score': score})
        # More shared words first; on a tie, the newer memory first.
        scored.sort(key=lambda m: (-m['score'], -m['id']))
        return scored[:limit]

    def count(self, scope: Scope) -> int:
        return len(self._visible(scope))
