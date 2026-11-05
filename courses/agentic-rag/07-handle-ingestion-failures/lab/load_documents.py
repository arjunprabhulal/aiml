"""Load a pinned local documentation snapshot. No network or model calls."""
from __future__ import annotations
import argparse
import hashlib
import json
import stat
from pathlib import Path, PurePosixPath

MAX_BYTES = 64 * 1024

class IngestionError(ValueError):
    """A source cannot satisfy the ingestion contract."""

def load_source(root: Path, source: dict) -> dict:
    """Validate bytes before decoding; do not silently substitute changed text."""
    relative = source.get('path', '')
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise IngestionError('invalid_path')
    parts = PurePosixPath(relative)
    if parts.is_absolute() or '..' in parts.parts or parts.suffix != '.md':
        raise IngestionError('invalid_path')
    root = root.resolve()
    candidate = root / relative
    # Reject all symlinks, including links that currently resolve within the root.
    for parent in [candidate, *candidate.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise IngestionError('symlink_source')
    path = candidate.resolve()
    if not path.is_relative_to(root):
        raise IngestionError('outside_root')
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise IngestionError('nonregular_source')
        # Bounded read avoids loading a large file before enforcing the limit.
        with path.open('rb') as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError as error:
        raise IngestionError('unreadable_source') from error
    if len(raw) > MAX_BYTES:
        raise IngestionError('size_limit')
    if hashlib.sha256(raw).hexdigest() != source.get('sha256'):
        raise IngestionError('hash_mismatch')
    try:
        body = raw.decode('utf-8')
    except UnicodeDecodeError as error:
        raise IngestionError('invalid_utf8') from error
    if not body.strip() or '\x00' in body:
        raise IngestionError('invalid_text')
    return {key: source[key] for key in ('source_id', 'path', 'title', 'sha256', 'version', 'url', 'fact_status') if key in source} | {'text': body.replace('\r\n', '\n')}

def read_manifest(path: Path) -> list[dict]:
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IngestionError('unreadable_manifest') from error
    if not isinstance(manifest, dict):
        raise IngestionError('invalid_manifest')
    sources = manifest.get('sources')
    if manifest.get('schema_version') != 1 or not isinstance(sources, list) or not sources:
        raise IngestionError('invalid_manifest')
    identities, paths = set(), set()
    for source in sources:
        if not isinstance(source, dict) or any(not isinstance(source.get(key), str) or not source[key] for key in ('source_id', 'path', 'title', 'sha256')):
            raise IngestionError('invalid_manifest')
        if any(key in source and (not isinstance(source[key], str) or not source[key]) for key in ('version', 'url', 'fact_status')):
            raise IngestionError('invalid_manifest')
        if source['source_id'] in identities or source['path'] in paths:
            raise IngestionError('duplicate_identity')
        identities.add(source['source_id']); paths.add(source['path'])
    return sources

def load_documents(manifest: Path) -> dict:
    sources = read_manifest(manifest)
    return {'schema_version': 1, 'execution_mode': 'offline-local-files',
            'documents': [load_source(manifest.parent, source) for source in sources]}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).parent / 'fixtures/source-manifest.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = load_documents(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'execution_mode': result['execution_mode'], 'loaded': len(result['documents'])}, sort_keys=True))

if __name__ == '__main__':
    main()
