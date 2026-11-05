"""Local evaluation policy, MLflow custom-flavor registry and release bundles."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import foundations as f
import workflow as w
import tracking

POLICY={'format':'return-release-policy-v1','purpose':'local analyst-preview exercise',
        'threshold':0.5,'minimum_accuracy':0.60,'minimum_gain_over_majority':2,
        'required_validation_rows':48,'final_test_allowed':False}


def candidate_files(pipeline_result):
    result=w.strict_json(pipeline_result)
    folder=Path(result['workspace'])/'tracker/runs'/result['run_id']/'workspace'
    return result,folder


def gate(cohort_path,model_path,policy=None):
    policy=dict(POLICY if policy is None else policy)
    if set(policy)!=set(POLICY) or policy['format']!=POLICY['format']:
        raise ValueError('unsupported policy schema')
    for field in ['threshold','minimum_accuracy']:
        value=policy[field]
        if type(value) not in (float,int) or not math.isfinite(value) or not 0<=value<=1:
            raise ValueError('invalid policy probability')
    if policy['threshold']!=0.5 or policy['final_test_allowed'] is not False:
        raise ValueError('this release requires the declared threshold and untouched final test')
    for key in ['minimum_gain_over_majority','required_validation_rows']:
        if type(policy[key]) is not int or policy[key]<0:raise ValueError('invalid policy count')
    model=w.load_model(model_path);report=w.evaluate(cohort_path,model_path)
    checks={'row_count':report['rows']==policy['required_validation_rows'],
            'minimum_accuracy':report['accuracy']>=policy['minimum_accuracy'],
            'majority_gain':report['correct']-report['majority_correct']>=policy['minimum_gain_over_majority'],
            'saved_threshold':model['settings']['threshold']==policy['threshold']}
    return {'policy':policy,'policy_sha256':f.digest(policy),'model_sha256':w.sha(model_path),
            'cohort_sha256':w.sha(cohort_path),'checks':checks,'passed':all(checks.values()),
            'validation':report,'cost_comparison':f.cost_report(cohort_path,model_path),
            'final_test_used':False,'permission':'local rollout exercise only'}


def package_candidate(pipeline_result,destination,policy=None):
    result,source=candidate_files(pipeline_result)
    if result['status']!='FINISHED' or w.sha(source/'outputs/candidate.json')!=result['model_sha256']:
        raise ValueError('pipeline model identity differs')
    decision=gate(source/'outputs/cohort.json',source/'outputs/candidate.json',policy)
    target=Path(destination);target.mkdir(parents=True)
    for name in ['candidate.json','cohort.json','validation.json']:
        shutil.copyfile(source/'outputs'/name,target/name)
    shutil.copyfile(source/'contract.json',target/'contract.json')
    # Include the exact trainer and application implementation for this artifact.
    for name in f.CORE_FILES:
        if name!='scenario.json':
            dest=target/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,dest)
    w.save(target/'gate.json',decision)
    from mlflow.models import Model
    metadata=Model();metadata.add_flavor('user_return',model_file='candidate.json',loader='release.load_bundle',format='return-model-v1');metadata.save(str(target/'MLmodel'))
    files={str(p.relative_to(target)):w.sha(p) for p in target.rglob('*') if p.is_file()}
    manifest={'format':'return-bundle-v1','project':w.PROJECT,'feature':f.FEATURE_CONTRACT,
              'run_id':result['run_id'],'model_sha256':result['model_sha256'],
              'policy_sha256':decision['policy_sha256'],'serving_code_sha256':w.sha(w.HERE/'serving.py'),
              'release_code_sha256':w.sha(Path(__file__)),'files':files}
    w.save(target/'bundle.json',manifest)
    load_bundle(target)
    return {'bundle_id':f.digest(manifest),'path':str(target.resolve()),'gate_passed':decision['passed'],
            'model_sha256':result['model_sha256'],'format':'custom MLflow user_return flavor; local loader'}


def load_bundle(path):
    path=Path(path);manifest=w.strict_json(path/'bundle.json')
    if manifest.get('format')!='return-bundle-v1' or manifest.get('project')!=w.PROJECT or manifest.get('feature')!=f.FEATURE_CONTRACT:
        raise ValueError('incompatible bundle contract')
    for key in ['serving_code_sha256','release_code_sha256']:
        file='serving.py' if key.startswith('serving') else 'release.py'
        if manifest[key]!=w.sha(w.HERE/file):raise ValueError('application code is incompatible with bundle')
    for name,expected in manifest['files'].items():
        p=(path/name).resolve()
        if not p.is_relative_to(path.resolve()) or w.sha(p)!=expected:raise ValueError('bundle artifact changed: '+name)
    if w.sha(path/'candidate.json')!=manifest['model_sha256']:raise ValueError('bundle model changed')
    model=w.load_model(path/'candidate.json');decision=w.strict_json(path/'gate.json')
    if f.digest(decision['policy'])!=manifest['policy_sha256']:raise ValueError('bundle policy changed')
    actual=gate(path/'cohort.json',path/'candidate.json',decision['policy'])
    if actual!=decision:raise ValueError('stored gate differs from fresh checks')
    return model,manifest,decision


def register(bundle,workspace):
    path=Path(bundle).resolve();_,manifest,decision=load_bundle(path)
    _,c,_=tracking.client(workspace)
    if c.get_run(manifest['run_id']).info.status!='FINISHED':raise ValueError('registry requires the original completed run in this store')
    name=w.PROJECT
    try:c.get_registered_model(name)
    except __import__('mlflow').exceptions.MlflowException as e:
        if e.error_code!='RESOURCE_DOES_NOT_EXIST':raise
        c.create_registered_model(name,description='Local user-return custom JSON flavor')
    version=c.create_model_version(name,source=path.as_uri(),run_id=manifest['run_id'],tags={'bundle_sha256':f.digest(manifest),'gate_passed':str(decision['passed']).lower(),'format':'user_return'})
    if decision['passed']:c.set_registered_model_alias(name,'review',version.version)
    return {'name':name,'version':str(version.version),'bundle_sha256':f.digest(manifest),
            'review_alias_selected':decision['passed'],'source':version.source,'model_sha256':manifest['model_sha256']}


def selected(workspace,version=None):
    from urllib.parse import urlparse,unquote
    _,c,_=tracking.client(workspace)
    item=c.get_model_version(w.PROJECT,str(version)) if version else c.get_model_version_by_alias(w.PROJECT,'review')
    url=urlparse(item.source)
    if url.scheme!='file' or url.netloc:raise ValueError('only local registry sources supported')
    path=Path(unquote(url.path));_,manifest,decision=load_bundle(path)
    if item.tags.get('bundle_sha256')!=f.digest(manifest):raise ValueError('registry binding differs')
    if not decision['passed']:raise ValueError('selected candidate failed its release gate')
    return path,str(item.version)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    x=sub.add_parser('gate');x.add_argument('--pipeline',type=Path,required=True);x.add_argument('--out',type=Path,required=True)
    x=sub.add_parser('package');x.add_argument('--pipeline',type=Path,required=True);x.add_argument('--destination',type=Path,required=True);x.add_argument('--out',type=Path,required=True)
    x=sub.add_parser('register');x.add_argument('--bundle',type=Path,required=True);x.add_argument('--workspace',type=Path,required=True);x.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    try:
        if a.command=='gate':
            _,root=candidate_files(a.pipeline);result=gate(root/'outputs/cohort.json',root/'outputs/candidate.json')
        elif a.command=='package':result=package_candidate(a.pipeline,a.destination)
        else:result=register(a.bundle,a.workspace)
        w.save(a.out,result);print(json.dumps(result,indent=2))
    except (ValueError,OSError) as e:p.exit(2,str(e)+'\n')


if __name__=='__main__':main()
