import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bind_release import FILES, Manifest, build, verify

HERE = Path(__file__).parent


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / 'bundle'
    shutil.copytree(HERE / 'bundle', root)
    return root


def edit_json(root, name, change):
    p = root / name; value = json.loads(p.read_text()); change(value)
    p.write_text(json.dumps(value))


def test_unchanged_recording_matches(bundle):
    assert verify(bundle, build(bundle)) == {'decision': 'match', 'findings': []}


def test_documentation_edit_requires_new_recording(bundle):
    manifest = build(bundle)
    edit_json(bundle, 'docs.json', lambda docs: docs[0].update(text='Changed tracker documentation.'))
    result = verify(bundle, manifest)
    assert result['decision'] == 'block'
    assert 'recording key differs: docs_sha' in result['findings']
    with pytest.raises(ValueError, match='docs_sha'):
        build(bundle)  # Rebuilding the manifest cannot make an old recording compatible.


def test_retrieval_depth_change_refuses_old_recording(bundle):
    p = bundle / 'assistant.py'; p.write_text(p.read_text().replace('K = 3', 'K = 4'))
    with pytest.raises(ValueError, match='k'):
        build(bundle)


def test_model_name_change_is_not_weight_identity(bundle):
    edit_json(bundle, 'run-config.json', lambda c: c.update(model='gemini-3.8-pro'))
    with pytest.raises(ValueError, match='model'):
        build(bundle)


def test_missing_case_cannot_hide_behind_same_key(bundle):
    manifest = build(bundle)
    edit_json(bundle, 'eval-run.json', lambda r: r['rows'].pop())
    assert 'eval case ids differ' in verify(bundle, manifest)['findings']
    with pytest.raises(ValueError, match='eval case ids differ'):
        build(bundle)


def test_missing_recording_entry_blocks(bundle):
    edit_json(bundle, 'recording.json', lambda r: r['entries'].pop('agent/backup'))
    with pytest.raises(ValueError, match='recording entry missing'):
        build(bundle)


def test_removed_and_edited_application_files_block(bundle):
    manifest = build(bundle)
    p = bundle / 'assistant.py'; p.write_text(p.read_text() + '\n# edit\n')
    assert 'file changed or missing: assistant.py' in verify(bundle, manifest)['findings']
    p.unlink()
    assert verify(bundle, manifest)['decision'] == 'block'


def test_manifest_cannot_omit_required_file(bundle):
    manifest = build(bundle)
    del manifest.files['assistant.py']
    with pytest.raises(ValueError, match='file set'):
        verify(bundle, manifest)


def test_unchanged_failed_quality_scores_still_match(bundle):
    # Compatibility isn't a pass-rate gate: retain every recorded failure.
    report = json.loads((bundle / 'eval-run.json').read_text())
    assert any(r['first_failure'] for r in report['rows'])
    assert verify(bundle, build(bundle))['decision'] == 'match'


def test_invalid_manifest_schema_refused():
    with pytest.raises(ValueError):
        Manifest(schema_version=2, files={}, recording_key={})


def test_saved_scenarios_reproduce():
    subprocess.run([sys.executable, str(HERE / 'record_release_checks.py'), '--check'], check=True, cwd=HERE)
