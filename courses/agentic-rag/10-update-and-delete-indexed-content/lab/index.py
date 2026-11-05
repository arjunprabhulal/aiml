"""Transactional local source/chunk maintenance with a real SQLite FTS5 index."""
import sqlite3


def connect(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS sources(source_id TEXT PRIMARY KEY, document_revision TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chunks(chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id), text TEXT NOT NULL);
    CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(chunk_id UNINDEXED, source_id UNINDEXED, text);
    """)
    return db


def replace_source(db, source, interrupt=False):
    sid = source["source_id"]
    with db:
        db.execute("DELETE FROM search_index WHERE source_id=?", (sid,))
        db.execute("DELETE FROM chunks WHERE source_id=?", (sid,))
        db.execute("INSERT INTO sources VALUES (?,?) ON CONFLICT(source_id) DO UPDATE SET document_revision=excluded.document_revision", (sid, source["document_revision"]))
        for chunk in source["chunks"]:
            row = (chunk["chunk_id"], sid, chunk["text"])
            db.execute("INSERT INTO chunks VALUES (?,?,?)", row)
            db.execute("INSERT INTO search_index VALUES (?,?,?)", row)
        if interrupt:
            raise InterruptedError("injected interruption before index commit")


def delete_source(db, source_id, interrupt=False):
    """Deleting a missing source is an explicit idempotent no-op."""
    with db:
        present = db.execute("SELECT 1 FROM sources WHERE source_id=?", (source_id,)).fetchone() is not None
        db.execute("DELETE FROM search_index WHERE source_id=?", (source_id,))
        db.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
        db.execute("DELETE FROM sources WHERE source_id=?", (source_id,))
        if interrupt:
            raise InterruptedError("injected interruption before deletion commit")
    return "deleted" if present else "missing-no-op"


def search(db, query):
    """Return lexical matches; no ranking or dense-vector claim."""
    return [dict(zip(("chunk_id", "source_id", "text"), row)) for row in db.execute("SELECT chunk_id,source_id,text FROM search_index WHERE search_index MATCH ? ORDER BY source_id,chunk_id", (query,))]


def state(db):
    return {table: [list(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1,2")] for table in ("sources", "chunks", "search_index")}
