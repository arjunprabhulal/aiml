"""Reproduce deterministic compatibility scenarios using unchanged saved model output."""
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from bind_release import Manifest, build, verify

HERE = Path(__file__).parent


def scenarios():
    rows = []
    for name in ('unchanged bundle', 'documentation edited', 'retrieval depth changed',
                 'generator name changed', 'case removed from report', 'application source edited'):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / 'bundle'
            shutil.copytree(HERE / 'bundle', root)
            manifest = build(root)
            if name == 'documentation edited':
                docs = json.loads((root / 'docs.json').read_text())
                docs[0]['text'] += ' A later documentation edit.'
                (root / 'docs.json').write_text(json.dumps(docs))
            elif name == 'retrieval depth changed':
                p = root / 'assistant.py'; p.write_text(p.read_text().replace('K = 3', 'K = 4'))
            elif name == 'generator name changed':
                p = root / 'run-config.json'; data = json.loads(p.read_text())
                data['model'] = 'gemini-3.8-pro'; p.write_text(json.dumps(data))
            elif name == 'case removed from report':
                p = root / 'eval-run.json'; data = json.loads(p.read_text())
                data['rows'].pop(); p.write_text(json.dumps(data))
            elif name == 'application source edited':
                p = root / 'assistant.py'; p.write_text(p.read_text() + '\n# application edit\n')
            rows.append({'scenario': name, **verify(root, manifest)})
    return {'mode': 'local compatibility checks; no new model calls', 'scenarios': rows}


if __name__ == '__main__':
    outputs = {'release-manifest.json': build(HERE / 'bundle').model_dump(mode='json'),
               'release-checks.json': scenarios()}
    for name, value in outputs.items():
        text = json.dumps(value, indent=2, sort_keys=True) + '\n'
        path = HERE / name
        if '--check' in sys.argv:
            if path.read_text() != text:
                raise ValueError(f'{name} differs; regenerate it')
        else:
            path.write_text(text)
    for row in outputs['release-checks.json']['scenarios']:
        print(f"{row['scenario']}: {row['decision']} ({len(row['findings'])} findings)")
