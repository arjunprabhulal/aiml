"""Bind one recorded tracker evaluation to its local application files.
Hashes detect differences; this is neither a signature nor a deployment check.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

FILES = ('assistant.py', 'evaluate.py', 'cases.json', 'docs.json', 'issues.json',
         'run-config.json', 'requirements.lock', 'recording.json', 'eval-run.json')


class Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: int = Field(default=1, ge=1, le=1)
    files: dict[str, str]
    recording_key: dict


def sha(value):
    # Match evaluate.py's existing recording-key serialization, including spaces.
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]


def read(root, name):
    return json.loads((root / name).read_text())


def current_key(root):
    # Read literal application settings without importing or executing the agent.
    settings = {}
    for node in ast.parse((root / 'assistant.py').read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ('PROMPT', 'K'):
                settings[node.targets[0].id] = ast.literal_eval(node.value)
    cases = read(root, 'cases.json')
    return {**read(root, 'run-config.json'),
            'cases': f"{cases['name']}@{cases['version']}", 'cases_sha': sha(cases),
            'docs_sha': sha({'docs': read(root, 'docs.json'), 'issues': read(root, 'issues.json')}),
            'prompt_sha': sha(settings['PROMPT']), 'k': settings['K']}


def digests(root):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in FILES}


def verify(root, manifest):
    if set(manifest.files) != set(FILES):
        raise ValueError('manifest file set differs from the required application bundle')
    findings = []
    for name, expected in manifest.files.items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            findings.append(f'file changed or missing: {name}')
    try:
        key = current_key(root)
        for name, other in [('manifest', manifest.recording_key),
                            ('recording', read(root, 'recording.json')['key']),
                            ('eval run', read(root, 'eval-run.json')['key'])]:
            for field in key.keys() | other.keys():
                if key.get(field) != other.get(field):
                    findings.append(f'{name} key differs: {field}')
        cases = read(root, 'cases.json')['cases']
        rows = read(root, 'eval-run.json')['rows']
        expected_ids = [c['id'] for c in cases]
        if sorted(r['id'] for r in rows) != sorted(expected_ids):
            findings.append('eval case ids differ')
        entries = read(root, 'recording.json')['entries']
        if any(f'{stage}/{case_id}' not in entries for case_id in expected_ids
               for stage in ('agent', 'tools', 'judge')):
            findings.append('recording entry missing')
    except (OSError, ValueError, KeyError, SyntaxError) as exc:
        findings.append(f'cannot read application bundle: {type(exc).__name__}')
    return {'decision': 'block' if findings else 'match', 'findings': sorted(findings)}


def build(root):
    manifest = Manifest(files=digests(root), recording_key=current_key(root))
    result = verify(root, manifest)
    if result['findings']:
        raise ValueError(result)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('build', 'verify'))
    parser.add_argument('--root', type=Path, default=Path('bundle'))
    parser.add_argument('--manifest', type=Path, default=Path('release-manifest.json'))
    args = parser.parse_args()
    if args.action == 'build':
        args.manifest.write_text(build(args.root).model_dump_json(indent=2) + '\n')
    else:
        result = verify(args.root, Manifest.model_validate_json(args.manifest.read_text()))
        print(json.dumps(result, indent=2))
        raise SystemExit(result['decision'] == 'block')
