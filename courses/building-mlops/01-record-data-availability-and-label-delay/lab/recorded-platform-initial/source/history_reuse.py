"""Retain feature vintages; join only values published by the prediction time.

Synthetic UTC minutes and supplied publication times model a trusted writer.
This SQLite exercise is not a production event-time or publication service.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from vendor.availability import instant, validate, check_id
from vendor.feature_math import Feature, compute

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
COUNT = Feature('user_events_1d', 1, 'user', 1, 'count')


def minute(value):
    seconds = (instant(value) - EPOCH).total_seconds()
    if seconds < 0 or seconds % 60:
        raise ValueError('fixture timestamps must be whole minutes since 2026-01-01 UTC')
    return int(seconds // 60)


def nonnegative(value):
    if type(value) is not int or not 0 <= value < 2**62:
        raise ValueError('time and age must be bounded nonnegative integer minutes')
    return value


def source_rows(events):
    validate([], events, [])
    return [{'event': index, 'user': e['entity'], 'item': 'unused',
             'event_minute': minute(e['event_at']), 'ingested_minute': minute(e['arrived_at'])}
            for index, e in enumerate(events)]


class History:
    def __init__(self, path=':memory:'):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS definitions (
                feature TEXT PRIMARY KEY, spec TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS batches (
                feature TEXT, cutoff INTEGER, published_at INTEGER, mode TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                PRIMARY KEY(feature, cutoff, published_at));
            CREATE TABLE IF NOT EXISTS history (
                feature TEXT, entity TEXT, cutoff INTEGER, published_at INTEGER,
                value INTEGER NOT NULL, PRIMARY KEY(feature, entity, cutoff, published_at));
            CREATE TABLE IF NOT EXISTS online (
                feature TEXT, entity TEXT, cutoff INTEGER NOT NULL, published_at INTEGER NOT NULL,
                value INTEGER NOT NULL, PRIMARY KEY(feature, entity));
        ''')

    def close(self):
        self.db.close()

    def materialize(self, events, cutoff, published_at, mode='as_known', feature=COUNT):
        cutoff = nonnegative(cutoff); published_at = nonnegative(published_at)
        if published_at < cutoff:
            raise ValueError('publication cannot precede its feature cutoff')
        if mode not in ('as_known', 'corrected'):
            raise ValueError('unknown availability mode')
        if (not isinstance(feature, Feature) or feature.entity != 'user'
                or type(feature.version) is not int or feature.version < 1
                or type(feature.window_days) is not int or feature.window_days < 1
                or feature.aggregation not in ('count', 'distinct_days')):
            raise ValueError('expected a versioned user-count or active-day feature')
        check_id(feature.name)
        # A corrected backfill still cannot use an event unavailable at publication.
        available = [e for e in source_rows(events) if e['ingested_minute'] <= published_at]
        values = compute(feature, available, cutoff, mode)
        source_hash = hashlib.sha256(json.dumps(sorted(events, key=lambda e: e['id']),
                                                sort_keys=True).encode()).hexdigest()
        key = f'{feature.name}@v{feature.version}'
        with self.db:
            old = self.db.execute('SELECT spec FROM definitions WHERE feature=?', (key,)).fetchone()
            if old and old['spec'] != feature.spec():
                raise ValueError('changed definition requires a new version')
            identity = (key, cutoff, published_at)
            batch = self.db.execute('SELECT mode,source_sha256 FROM batches WHERE feature=? '
                                    'AND cutoff=? AND published_at=?', identity).fetchone()
            if batch:
                if tuple(batch) != (mode, source_hash):
                    raise ValueError('conflicting publication identity')
                return key  # Identical retry; never rewrite a published vintage.
            latest = self.db.execute('SELECT MAX(published_at) FROM batches WHERE feature=?', (key,)).fetchone()[0]
            if latest is not None and published_at < latest:
                raise ValueError('cannot backdate publication; use the actual later availability time')
            self.db.execute('INSERT OR IGNORE INTO definitions VALUES (?,?)', (key, feature.spec()))
            self.db.execute('INSERT INTO batches VALUES (?,?,?,?,?)', (*identity, mode, source_hash))
            for entity, value in values.items():
                self.db.execute('INSERT INTO history VALUES (?,?,?,?,?)', (key, entity, cutoff, published_at, value))
                self.db.execute('''INSERT INTO online VALUES (?,?,?,?,?)
                    ON CONFLICT(feature,entity) DO UPDATE SET
                        cutoff=excluded.cutoff, published_at=excluded.published_at, value=excluded.value
                    WHERE excluded.cutoff > online.cutoff OR
                        (excluded.cutoff=online.cutoff AND excluded.published_at>online.published_at)''',
                    (key, entity, cutoff, published_at, value))
        return key

    def point_in_time(self, feature, entity, predict_at):
        nonnegative(predict_at); check_id(feature); check_id(entity)
        query = (Path(__file__).resolve().parent / 'join.sql').read_text()
        row = self.db.execute(query, (feature, entity, predict_at, predict_at)).fetchone()
        return dict(row) if row else None

    def join(self, observations, feature):
        validate(observations, [], [])
        # Preserve one row per observation, even when the feature is missing.
        return [dict(row, feature=self.point_in_time(feature, row['entity'], minute(row['predict_at'])))
                for row in observations]

    def read_online(self, feature, entity, now, max_age):
        nonnegative(now); nonnegative(max_age); check_id(feature); check_id(entity)
        row = self.db.execute('SELECT value,cutoff,published_at FROM online WHERE feature=? AND entity=?',
                              (feature, entity)).fetchone()
        if row is None:
            return {'status': 'missing', 'value': None, 'age_minutes': None}
        age = now - row['cutoff']
        if row['cutoff'] > now or row['published_at'] > now:
            status = 'unavailable'
        else:
            status = 'fresh' if age <= max_age else 'stale'
        return dict(row, status=status, value=row['value'] if status == 'fresh' else None, age_minutes=age)
