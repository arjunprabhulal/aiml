"""Persist a pinned ingestion job, one atomic source unit at a time."""
import hashlib
import json
import sqlite3


class IngestionError(ValueError):
    pass


def connect(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, input_sha256 TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sources(source_id TEXT PRIMARY KEY, document_revision TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chunks(chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id), text TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS checkpoints(job_id TEXT NOT NULL REFERENCES jobs(job_id), source_id TEXT NOT NULL REFERENCES sources(source_id), document_revision TEXT NOT NULL, PRIMARY KEY(job_id, source_id));
    """)
    return db


def ingest(db, snapshot, job_id, interrupt_source=None):
    """An injected interruption raises before commit, leaving no partial source."""
    input_digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    with db:
        other = db.execute("SELECT job_id FROM jobs WHERE job_id<>?", (job_id,)).fetchone()
        if other:
            raise IngestionError("database belongs to another job; use a new database")
        previous = db.execute("SELECT snapshot_id,input_sha256 FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if previous and previous != (snapshot["snapshot_id"], input_digest):
            raise IngestionError("job snapshot changed; start a new job")
        db.execute("INSERT OR IGNORE INTO jobs VALUES (?,?,?)", (job_id, snapshot["snapshot_id"], input_digest))
    actions = []
    for source in snapshot["documents"]:
        sid, revision = source["source_id"], source["document_revision"]
        with db:
            done = db.execute("SELECT document_revision FROM checkpoints WHERE job_id=? AND source_id=?", (job_id, sid)).fetchone()
            stored = db.execute("SELECT document_revision FROM sources WHERE source_id=?", (sid,)).fetchone()
            expected = sorted((c["chunk_id"], sid, c["text"]) for c in source["chunks"])
            actual = list(db.execute("SELECT chunk_id,source_id,text FROM chunks WHERE source_id=? ORDER BY chunk_id", (sid,)))
            if done:
                if done[0] != revision or stored != (revision,) or actual != expected:
                    raise IngestionError("checkpoint does not match stored source")
                actions.append({"source_id": sid, "action": "skipped"})
                continue
            if stored and stored != (revision,):
                raise IngestionError("existing source revision differs; use update workflow")
            if stored and actual != expected:
                raise IngestionError("existing chunks differ from supplied source")
            db.execute("INSERT OR IGNORE INTO sources VALUES (?,?)", (sid, revision))
            if not stored:
                for chunk in source["chunks"]:
                    db.execute("INSERT INTO chunks VALUES (?,?,?)", (chunk["chunk_id"], sid, chunk["text"]))
            if sid == interrupt_source:
                raise InterruptedError("injected interruption before source commit")
            db.execute("INSERT INTO checkpoints VALUES (?,?,?)", (job_id, sid, revision))
        actions.append({"source_id": sid, "action": "committed"})
    return actions


def state(db):
    return {table: [list(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1,2")] for table in ("jobs", "sources", "chunks", "checkpoints")}
