"""Compare deliberate local fixture revisions; never claim upstream updates."""
import argparse
import json
from pathlib import Path
from version_documents import build_snapshot, compare

def run(output: Path):
    root = Path(__file__).parent
    snapshots = {name: build_snapshot(root / 'fixtures' / name / 'source-manifest.json') for name in ('initial','text-change','metadata-change')}
    comparisons = {name: compare(snapshots['initial'], snapshots[name]) for name in ('text-change','metadata-change')}
    result = {'execution_mode': 'offline-local-files', 'scope': 'deliberate local fixture changes; no upstream refresh or model execution', 'snapshots': snapshots, 'comparisons': comparisons}
    output.mkdir(parents=True, exist_ok=True)
    for name, snapshot in snapshots.items():
        (output / f'{name}.json').write_text(json.dumps(snapshot, indent=2)+'\n', encoding='utf-8')
    (output / 'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'execution_mode': result['execution_mode'], 'comparisons': comparisons}, sort_keys=True))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
