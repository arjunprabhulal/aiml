"""Preserve raw JSON Lines records, apply the existing event contract and gate a batch."""
import argparse
import base64
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
from availability import validate as validate_event

SCHEMA_VERSION = 'event-v1'
RULES_VERSION = '1'
MAX_LINE_BYTES = 512
SCHEMA_SHA = hashlib.sha256((Path(__file__).parent / 'vendor/availability.py').read_bytes()).hexdigest()


class DuplicateKey(ValueError): pass
class NonstandardConstant(ValueError): pass


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKey('duplicate JSON key: ' + key)
        value[key] = item
    return value


def reject_constant(value):
    raise NonstandardConstant('nonstandard JSON constant: ' + value)


@dataclass
class Entry:
    line: int
    raw: bytes
    record: dict | None = None
    reasons: list = field(default_factory=list)

    def reject(self, code, detail):
        self.reasons.append({'code': code, 'detail': detail})


def validate_batch(raw, max_line_bytes=MAX_LINE_BYTES):
    if not isinstance(raw, bytes):
        raise ValueError('input must be the original bytes')
    if type(max_line_bytes) is not int or not 1 <= max_line_bytes <= 1_048_576:
        raise ValueError('invalid line-byte limit')
    entries, identities = [], defaultdict(list)
    for number, blob in enumerate(io.BytesIO(raw), 1):
        entry = Entry(number, blob); entries.append(entry)
        if len(blob) > max_line_bytes:
            entry.reject('line_too_large', f'{len(blob)} bytes exceeds {max_line_bytes}')
            continue
        if not blob.strip(b' \t\r\n'):
            entry.reject('blank_record', 'JSON Lines needs one value on each line')
            continue
        try:
            value = json.loads(blob.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=reject_constant)
        except UnicodeError:
            entry.reject('invalid_utf8', 'line is not UTF-8'); continue
        except DuplicateKey as error:
            entry.reject('duplicate_json_key', str(error)); continue
        except NonstandardConstant as error:
            entry.reject('nonstandard_json_constant', str(error)); continue
        except json.JSONDecodeError as error:
            entry.reject('malformed_json', error.msg); continue
        if not isinstance(value, dict):
            entry.reject('record_must_be_object', 'valid JSON is not necessarily a valid event'); continue
        entry.record = value
        identity = value.get('id')
        if isinstance(identity, str) and 1 <= len(identity) <= 100:
            identities[identity].append(entry)
        try:
            validate_event([], [value], [])
        except ValueError as error:
            entry.reject('event_contract', str(error))
    # Refuse the entire parseable identity group, even when one row has another error.
    for identity, group in identities.items():
        if len(group) > 1:
            for entry in group:
                entry.reject('duplicate_event_id', identity)
    accepted = [entry for entry in entries if not entry.reasons]
    quarantined = [entry for entry in entries if entry.reasons]
    return {'source': raw, 'entries': entries, 'accepted': accepted, 'quarantined': quarantined,
            'max_line_bytes': max_line_bytes,
            'status': 'ready' if entries and not quarantined else 'blocked'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_batch(batch, output_dir):
    target = Path(output_dir)
    target.mkdir()  # Refuse an existing directory rather than mix or replace runs.
    files = {'source.bin': batch['source'], 'accepted.jsonl': b''.join(e.raw for e in batch['accepted'])}
    quarantined = [{'source_line': e.line, 'raw_sha256': sha(e.raw),
                    'raw_base64': base64.b64encode(e.raw).decode(), 'reasons': e.reasons}
                   for e in batch['quarantined']]
    files['quarantine.jsonl'] = ''.join(json.dumps(e, sort_keys=True) + '\n' for e in quarantined).encode()
    for name, raw in files.items():
        (target / name).write_bytes(raw)
    manifest = {'schema_version': SCHEMA_VERSION, 'schema_implementation_sha256': SCHEMA_SHA,
                'rules_version': RULES_VERSION, 'max_line_bytes': batch['max_line_bytes'],
                'source_sha256': sha(batch['source']), 'source_lines': len(batch['entries']),
                'accepted': len(batch['accepted']), 'quarantined': len(batch['quarantined']),
                'accepted_source_lines': [e.line for e in batch['accepted']],
                'status': batch['status'],
                'training_file': 'accepted.jsonl' if batch['status'] == 'ready' else None,
                'batch_reasons': ['empty_batch'] if not batch['entries'] else ['invalid_records'] if batch['quarantined'] else [],
                'reason_counts': dict(sorted(Counter(r['code'] for e in batch['quarantined'] for r in e.reasons).items())),
                'files': {name: sha(raw) for name, raw in files.items()}}
    # Written last: a partially written staging directory must not look ready.
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    batch = validate_batch(args.input.read_bytes())
    manifest = write_batch(batch, args.out_dir)
    print(f"{manifest['status']}: accepted={manifest['accepted']}; quarantined={manifest['quarantined']}")
    raise SystemExit(0 if manifest['status'] == 'ready' else 1)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(f'input or staging error: {error}')
