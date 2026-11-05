"""Quarantine bad local sources; explicitly report partial ingestion."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from load_documents import IngestionError, load_source, read_manifest

def ingest(manifest: Path) -> dict:
    # An invalid manifest fails the whole batch before any source is loaded.
    sources = read_manifest(manifest)
    documents, failures = [], []
    for source in sources:
        try:
            documents.append(load_source(manifest.parent, source))
        except IngestionError as error:
            failures.append({'source_id': source['source_id'], 'path': source['path'], 'error': str(error)})
    return {'schema_version': 1, 'execution_mode': 'offline-local-files',
            'status': 'partial' if failures and documents else 'failed' if failures else 'complete',
            'documents': documents, 'failures': failures}

def failure_exercise(manifest: Path) -> dict:
    """Mutate temporary copies only; leave the pinned source snapshot untouched."""
    sources = read_manifest(manifest)
    if len(sources) < 4:
        raise IngestionError('exercise_requires_four_sources')
    # Validate the entire snapshot before staging; never copy unchecked paths.
    for source in sources:
        load_source(manifest.parent, source)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for source in sources:
            target = root / source['path']; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((manifest.parent / source['path']).read_bytes())
        # Changed bytes are rejected before decoding, preserving the pinned contract.
        (root / sources[1]['path']).write_bytes(b'changed after snapshot')
        (root / sources[2]['path']).unlink()
        invalid = b'\xff'
        (root / sources[3]['path']).write_bytes(invalid)
        sources[3] = dict(sources[3], sha256=hashlib.sha256(invalid).hexdigest())
        copy = root / 'manifest.json'
        copy.write_text(json.dumps({'schema_version': 1, 'sources': sources}))
        return ingest(copy)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).parent / 'fixtures/source-manifest.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exercise-failures', action='store_true')
    args = parser.parse_args()
    result = failure_exercise(args.manifest) if args.exercise_failures else ingest(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'loaded': len(result['documents']), 'failures': result['failures']}, sort_keys=True))
    # Partial completion is never advertised as full success to shell automation.
    raise SystemExit(0 if result['status'] == 'complete' else 2)

if __name__ == '__main__': main()
