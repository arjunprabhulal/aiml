"""Principal/purpose-scoped memory with revision, expiry and deletion."""
from core import load
import sqlite3


class Memory:
    def __init__(self, path=':memory:', *, clock):
        self.db = sqlite3.connect(path)
        self.clock = clock
        self.db.execute('''CREATE TABLE IF NOT EXISTS memory (
            principal TEXT NOT NULL,purpose TEXT NOT NULL,key TEXT NOT NULL,
            revision INTEGER NOT NULL,value TEXT NOT NULL,source TEXT NOT NULL,
            expires INTEGER NOT NULL,PRIMARY KEY(principal,purpose,key,revision))''')

    def put(self, principal, purpose, key, value, *, source, ttl):
        if not all(isinstance(x, str) and x.strip() and len(x) <= 500
                   for x in (principal, purpose, key, value, source)):
            raise ValueError('memory fields must be nonempty bounded strings')
        if type(ttl) is not int or not 1 <= ttl <= 86400:
            raise ValueError('ttl must be 1..86400 seconds')
        with self.db:
            old = self.db.execute('SELECT MAX(revision) FROM memory WHERE principal=? AND purpose=? AND key=?',
                                  (principal, purpose, key)).fetchone()[0] or 0
            self.db.execute('INSERT INTO memory VALUES (?,?,?,?,?,?,?)',
                            (principal, purpose, key, old + 1, value, source, self.clock() + ttl))
        return old + 1

    def get(self, principal, purpose, key):
        row = self.db.execute('''SELECT value,source,revision,expires FROM memory
            WHERE principal=? AND purpose=? AND key=? ORDER BY revision DESC LIMIT 1''',
                              (principal, purpose, key)).fetchone()
        # Never fall back to a superseded revision when the newest one expires.
        if row is None or row[3] <= self.clock():
            return None
        return dict(zip(('value', 'source', 'revision', 'expires'), row))

    def delete(self, principal, purpose, key):
        with self.db:
            cursor = self.db.execute('DELETE FROM memory WHERE principal=? AND purpose=? AND key=?',
                                     (principal, purpose, key))
        return cursor.rowcount

    def close(self):
        self.db.close()


def main():
    example = load('memory-scenario.json')
    now = [example['initial_time']]
    memory = Memory(clock=lambda: now[0])
    principal, purpose, key = (example[k] for k in ('principal', 'purpose', 'key'))
    try:
        memory.put(principal, purpose, key, example['initial'], source='user message', ttl=example['initial_ttl'])
        revision = memory.put(principal, purpose, key, example['correction'], source='user correction', ttl=example['correction_ttl'])
        print('corrected:', memory.get(principal, purpose, key)['value'], '| revision:', revision)
        print('other principal:', memory.get('bob', purpose, key))
        now[0] += example['correction_ttl']
        print('at expiry:', memory.get(principal, purpose, key))
        print('deleted revisions:', memory.delete(principal, purpose, key))
        print('remaining rows:', memory.db.execute('SELECT COUNT(*) FROM memory').fetchone()[0])
    finally:
        memory.close()


if __name__ == '__main__':
    main()
