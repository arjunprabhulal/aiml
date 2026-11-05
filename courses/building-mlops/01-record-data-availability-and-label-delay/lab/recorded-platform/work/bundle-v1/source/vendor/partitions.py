"""Inspect row, entity and temporal boundaries; no model is trained."""
import hashlib
from datetime import datetime, timezone

NAMES = ('training', 'validation', 'test')
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
TRAIN_END = datetime(2026, 1, 7, tzinfo=timezone.utc)
VALIDATION_START = datetime(2026, 1, 8, tzinfo=timezone.utc)
VALIDATION_END = datetime(2026, 1, 10, tzinfo=timezone.utc)
TEST_START = datetime(2026, 1, 11, tzinfo=timezone.utc)
END = datetime(2026, 1, 13, tzinfo=timezone.utc)
SALT = 'mlops-evaluation-splits-v1'
MODES = ('row_hash', 'entity_hash', 'future', 'unseen_future')


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError('observation time must be an ISO UTC timestamp') from error
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError('observation time must have a UTC offset')
    return result


def validate(rows):
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'entity', 'observed_at'}:
            raise ValueError('each row needs exactly id, entity and observed_at')
        for key in ('id', 'entity'):
            if not isinstance(row[key], str) or not row[key] or len(row[key]) > 100:
                raise ValueError('IDs must be bounded nonempty strings')
        if row['id'] in seen:
            raise ValueError('duplicate row ID')
        seen.add(row['id'])
        instant(row['observed_at'])


def hash_partition(key):
    value = int.from_bytes(hashlib.sha256((SALT + ':' + key).encode()).digest()[:8])
    # Integer intervals avoid rounding the largest digest to an unassigned 1.0.
    for name, numerator, denominator in [('training', 7, 10), ('validation', 17, 20), ('test', 1, 1)]:
        if value * denominator < numerator * 2**64:
            return name
    raise AssertionError('unreachable digest endpoint')


def time_partition(at):
    if START <= at < TRAIN_END:
        return 'training'
    if VALIDATION_START <= at < VALIDATION_END:
        return 'validation'
    if TEST_START <= at < END:
        return 'test'
    return 'excluded'


def partition(rows, mode):
    if mode not in MODES:
        raise ValueError('unknown evaluation target')
    validate(rows)
    parts = {name: [] for name in (*NAMES, 'excluded')}
    for row in rows:
        entity_part = hash_partition(row['entity'])
        time_part = time_partition(instant(row['observed_at']))
        if mode == 'row_hash':
            name = hash_partition(row['id'])
        elif mode == 'entity_hash':
            name = entity_part
        elif mode == 'future':
            name = time_part
        else:
            name = time_part if entity_part == time_part else 'excluded'
        parts[name].append(row)
    if any(not parts[name] for name in NAMES):
        raise ValueError('each evaluation partition needs at least one row')
    return {name: sorted(items, key=lambda row: row['id']) for name, items in parts.items()}


def describe(parts):
    entities = {name: {row['entity'] for row in parts[name]} for name in NAMES}
    return {'rows': {name: len(items) for name, items in parts.items()},
            'entities': {name: len(items) for name, items in entities.items()},
            'train_validation_shared_entities': len(entities['training'] & entities['validation']),
            'train_test_shared_entities': len(entities['training'] & entities['test']),
            'ranges': {name: {'first': min(instant(row['observed_at']) for row in parts[name]).isoformat().replace('+00:00', 'Z'),
                              'last': max(instant(row['observed_at']) for row in parts[name]).isoformat().replace('+00:00', 'Z')} for name in NAMES}}
