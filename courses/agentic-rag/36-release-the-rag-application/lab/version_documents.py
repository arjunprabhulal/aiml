"""Version pinned documentation bytes, metadata, paragraphs and corpus snapshots."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from load_documents import IngestionError, load_documents

CHUNKER = {'name': 'paragraphs', 'version': 1, 'newline_policy': 'CRLF-to-LF', 'separator': 'blank-line'}
METADATA_KEYS = ('path', 'title', 'version', 'url', 'fact_status')

def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()

def paragraphs(text: str):
    """Yield exact normalized-text slices with 1-based inclusive line spans."""
    lines = text.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.strip():
            if start is None:
                start = index
        elif start is not None:
            yield start + 1, index, ''.join(lines[start:index])
            start = None
    if start is not None:
        yield start + 1, len(lines), ''.join(lines[start:])

def version_document(document: dict, config: dict) -> dict:
    metadata = {key: document[key] for key in METADATA_KEYS if key in document}
    metadata_sha256 = canonical_hash(metadata)
    revision = canonical_hash({'source_id': document['source_id'], 'raw_sha256': document['sha256'], 'metadata_sha256': metadata_sha256})
    chunks = []
    for start, end, text in paragraphs(document['text']):
        text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        identity = {'document_revision': revision, 'chunker': config, 'start_line': start, 'end_line': end, 'text_sha256': text_hash}
        chunks.append({'chunk_id': canonical_hash(identity), 'source_id': document['source_id'], 'document_revision': revision,
                       'start_line': start, 'end_line': end, 'text': text, 'text_sha256': text_hash})
    return {**document, 'metadata_sha256': metadata_sha256, 'document_revision': revision, 'chunks': chunks}

def snapshot_identity(documents: list, config: dict) -> str:
    # Bind normalized text, metadata and every chunk too, not only claimed revisions.
    return canonical_hash({'schema_version': 1, 'chunker': config, 'documents': documents})

def build_snapshot(manifest: Path, chunker: dict | None = None) -> dict:
    config = dict(CHUNKER if chunker is None else chunker)
    if canonical_hash(config) != canonical_hash(CHUNKER):
        raise IngestionError('unsupported_chunker')
    loaded = load_documents(manifest)['documents']
    documents = [version_document(document, config) for document in sorted(loaded, key=lambda d: d['source_id'])]
    return {'schema_version': 1, 'execution_mode': 'offline-local-files', 'chunker': config,
            'snapshot_id': snapshot_identity(documents, config), 'documents': documents}

def validate_snapshot(snapshot: dict) -> dict:
    """Reject inconsistent saved artifacts; this does not authenticate raw files.

    Original byte hashes were checked while loading files. Normalized saved text
    cannot reconstruct original CRLF bytes, so this validator checks its canonical
    identity and internal derivations, not the original files or their provenance.
    """
    try:
        if not isinstance(snapshot, dict) or type(snapshot.get('schema_version')) is not int or snapshot['schema_version'] != 1:
            raise ValueError()
        if snapshot.get('execution_mode') != 'offline-local-files' or canonical_hash(snapshot.get('chunker')) != canonical_hash(CHUNKER):
            raise ValueError()
        documents = snapshot['documents']
        if not isinstance(documents, list) or not documents:
            raise ValueError()
        seen_ids, seen_paths = set(), set()
        allowed = ('source_id', 'path', 'title', 'sha256', 'version', 'url', 'fact_status', 'text')
        for document in documents:
            if not isinstance(document, dict):
                raise ValueError()
            original = {key: document[key] for key in allowed if key in document}
            if any(not isinstance(original.get(key), str) or not original[key] for key in ('source_id','path','title','sha256','text')):
                raise ValueError()
            if any(key in original and (not isinstance(original[key],str) or not original[key]) for key in ('version','url','fact_status')):
                raise ValueError()
            if len(original['sha256']) != 64 or any(c not in '0123456789abcdef' for c in original['sha256']):
                raise ValueError()
            if len(original['text'].encode('utf-8')) > 65536 or not original['text'].strip() or '\x00' in original['text'] or '\r\n' in original['text']:
                raise ValueError()
            if original['source_id'] in seen_ids or original['path'] in seen_paths:
                raise ValueError()
            seen_ids.add(original['source_id']); seen_paths.add(original['path'])
            if canonical_hash(document) != canonical_hash(version_document(original, CHUNKER)):
                raise ValueError()
        if documents != sorted(documents, key=lambda d:d['source_id']):
            raise ValueError()
        if snapshot.get('snapshot_id') != snapshot_identity(documents, CHUNKER):
            raise ValueError()
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError) as error:
        raise IngestionError('invalid_snapshot') from error
    return snapshot

def compare(before: dict, after: dict) -> dict:
    previous = {d['source_id']: d for d in before['documents']}
    current = {d['source_id']: d for d in after['documents']}
    return {'snapshot_changed': before['snapshot_id'] != after['snapshot_id'],
            'added': sorted(current.keys() - previous.keys()), 'removed': sorted(previous.keys() - current.keys()),
            'changed': [{'source_id': key, 'raw_bytes_changed': previous[key]['sha256'] != current[key]['sha256'],
                         'metadata_changed': previous[key]['metadata_sha256'] != current[key]['metadata_sha256'],
                         'chunk_ids_changed': [c['chunk_id'] for c in previous[key]['chunks']] != [c['chunk_id'] for c in current[key]['chunks']]}
                        for key in sorted(previous.keys() & current.keys()) if previous[key]['document_revision'] != current[key]['document_revision']]}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).parent / 'fixtures/initial/source-manifest.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build_snapshot(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'snapshot_id': result['snapshot_id'], 'documents': len(result['documents']), 'chunks': sum(len(d['chunks']) for d in result['documents'])}, sort_keys=True))

if __name__ == '__main__': main()
