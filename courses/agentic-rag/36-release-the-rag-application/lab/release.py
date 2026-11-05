"""Sealed local artifacts and runtime smoke checks, not a production deployer."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile

FILES = ('api.py','app.py','service.py','tools.py','refine.py','limits.py',
         'bm25.py','version_documents.py','load_documents.py','loopback.py',
         'serve.py','requirements.txt','requirements.lock','LICENSE',
         'fixtures/snapshot.json','fixtures/development-cases.json',
         'evaluator.py','compare.py','fixtures/task-evaluation.json')
QUESTION = 'Will write_text replace the contents of an existing file?'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()

def package(source, destination, label):
    """Copy the explicit runtime closure into a new immutable candidate directory."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('destination_exists')
    if not isinstance(label,str) or not label or len(label)>64:
        raise ValueError('invalid_label')
    destination.mkdir(parents=True)
    for name in FILES:
        path=source/name
        if path.is_symlink() or not path.is_file():
            raise ValueError('invalid_source_file')
        target=destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
    (destination/'release-config.json').write_bytes(canonical({'schema':1,'label':label,'deployment':'local-staging-only'}))
    manifest={'schema':1,'files':{name:digest((destination/name).read_bytes()) for name in (*FILES,'release-config.json')}}
    release_id=digest(canonical(manifest))
    (destination/'manifest.json').write_bytes(canonical(manifest))
    verify(destination,release_id)
    return release_id

def verify(directory, expected_id):
    """The caller retains expected_id separately from the candidate it checks."""
    directory=Path(directory)
    if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob('*')):
        raise ValueError('unexpected_bundle_entry')
    manifest=json.loads((directory/'manifest.json').read_bytes())
    if set(manifest)!= {'schema','files'} or type(manifest['schema']) is not int or manifest['schema']!=1:
        raise ValueError('manifest_schema')
    if digest(canonical(manifest))!=expected_id:
        raise ValueError('release_identity_mismatch')
    expected=set(FILES)|{'release-config.json'}
    if set(manifest['files'])!=expected:
        raise ValueError('file_closure_mismatch')
    actual={str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file()}
    if actual != expected|{'manifest.json'} or any(p.is_symlink() for p in directory.rglob('*')):
        raise ValueError('unexpected_bundle_entry')
    for name,sha in manifest['files'].items():
        if digest((directory/name).read_bytes())!=sha:
            raise ValueError('file_hash_mismatch')
    return manifest

def smoke(directory, expected_id):
    """Start the actual staged service, send real HTTP, then reap its child."""
    directory=Path(directory)
    verify(directory,expected_id)
    spec=importlib.util.spec_from_file_location('staged_loopback',directory/'loopback.py')
    harness=importlib.util.module_from_spec(spec)
    # Load the helper without writing __pycache__ inside the sealed candidate.
    exec(compile((directory/'loopback.py').read_bytes(), str(directory/'loopback.py'), 'exec'), harness.__dict__)
    # Prevent the Python child from adding bytecode to the sealed runtime closure.
    previous=os.environ.get('PYTHONDONTWRITEBYTECODE')
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    try:
        with harness.running_server() as (client,lifecycle):
            health=client.get('/health')
            valid=client.post('/retrieve',json={'question':QUESTION})
            invalid=client.post('/retrieve',json={'question':QUESTION,'max_steps':True})
            body=valid.json()
            checks={'health':health.status_code==200,
                    'valid_request':valid.status_code==200 and body['status']=='completed',
                    'strict_refusal':invalid.status_code==422,
                    'wire_digest':digest(valid.content)==valid.headers.get('X-Retrieval-Body-SHA256'),
                    'no_model':body['model_called'] is False}
    finally:
        if previous is None:os.environ.pop('PYTHONDONTWRITEBYTECODE',None)
        else:os.environ['PYTHONDONTWRITEBYTECODE']=previous
    verify(directory,expected_id)
    return {'release_id':expected_id,'checks':checks,'passed':all(checks.values()),
            'scope':'local-runtime-smoke-only','lifecycle':lifecycle}

def atomic_state(path, value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.candidate-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if Path(name).exists():Path(name).unlink()

def task_gate(directory, expected_id):
    """Recheck the pinned preceding task report; do not run a model or rerank it."""
    from evaluator import release_gate
    directory=Path(directory)
    verify(directory,expected_id)
    raw=(directory/'fixtures/task-evaluation.json').read_bytes()
    saved=json.loads(raw)
    report=saved['normal']
    snapshot=json.loads((directory/'fixtures/snapshot.json').read_bytes())
    if report['identity']['corpus_id']!=snapshot['snapshot_id']:
        return {'decision':'NOTCOMPARABLE','release_id':expected_id,'reason':'corpus_mismatch'}
    result=release_gate(report,report['identity'],'scripted_refinement')
    return {'decision':result['status'],'release_id':expected_id,'report_sha256':digest(raw),
            'result':result,'scope':'archived-scripted-development-fixtures-only'}

def promote(pointer, directory, expected_id, smoke_record):
    """Move only a local artifact pointer; this does not switch running traffic."""
    verify(directory,expected_id)
    names={'health','valid_request','strict_refusal','wire_digest','no_model'}
    checks=smoke_record.get('checks',{})
    if (smoke_record.get('release_id')!=expected_id or smoke_record.get('passed') is not True
        or set(checks)!=names or any(value is not True for value in checks.values())):
        raise ValueError('smoke_not_accepted')
    if task_gate(directory,expected_id)['decision']!='PASS':
        raise ValueError('task_gate_not_accepted')
    pointer=Path(pointer)
    old=json.loads(pointer.read_bytes()) if pointer.exists() else None
    state={'current':{'directory':str(Path(directory).resolve()),'release_id':expected_id},
           'previous':old['current'] if old else None}
    atomic_state(pointer,state)
    return state

def rollback(pointer):
    pointer=Path(pointer);state=json.loads(pointer.read_bytes());old=state.get('previous')
    if not old:raise ValueError('no_previous_release')
    verify(old['directory'],old['release_id'])
    restored={'current':old,'previous':state['current']}
    atomic_state(pointer,restored)
    return restored
