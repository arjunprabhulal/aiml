"""Execute and track the real user-return trainer in a local MLflow store."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import foundations as f
import workflow as w


def client(workspace):
    # Explicit local SQLite and file artifacts; no provider credentials or cloud URI.
    os.environ['MLFLOW_ENABLE_ASYNC_LOGGING']='false'
    os.environ['MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING']='false'
    os.environ['MLFLOW_DISABLE_TELEMETRY']='true'
    import mlflow
    uri='sqlite:///'+str((Path(workspace).resolve()/'tracking.sqlite'))
    mlflow.set_tracking_uri(uri)
    c=mlflow.MlflowClient(tracking_uri=uri)
    experiment=c.get_experiment_by_name(w.PROJECT)
    if experiment is None:
        artifact=(Path(workspace).resolve()/'artifacts');artifact.mkdir(parents=True,exist_ok=True)
        experiment_id=c.create_experiment(w.PROJECT,artifact_location=artifact.as_uri())
    else:experiment_id=experiment.experiment_id
    return mlflow,c,experiment_id


def execute(source, workspace, fail_before_training=False, prepared_cohort=None):
    workspace=Path(workspace).resolve();workspace.mkdir(parents=True,exist_ok=True)
    mlflow,c,experiment_id=client(workspace)
    with mlflow.start_run(experiment_id=experiment_id) as run:
        run_id=run.info.run_id;folder=workspace/'runs'/run_id
        manifest=f.snapshot(source,folder/'workspace')
        if w.sha(folder/'workspace/scenario.json')!=manifest['dataset_sha256']:
            raise ValueError('copied dataset differs from selected identity')
        for name,expected in manifest['implementation'].items():
            if w.sha(folder/'workspace'/name)!=expected:
                raise ValueError('copied source differs from selected identity: '+name)
        runtime={'python':sys.version.split()[0],
                 'packages':{name:importlib.metadata.version(name) for name in ['mlflow-skinny','SQLAlchemy']},
                 'contract_id':f.digest(manifest),'source':manifest,
                 'tracker_sha256':w.sha(Path(__file__))}
        w.save(folder/'runtime.json',runtime)
        mlflow.log_params({'project':w.PROJECT,'feature':w.FEATURE,'epochs':w.baseline.EPOCHS,
                           'learning_rate':w.baseline.LEARNING_RATE,'threshold':0.5,
                           'contract_id':f.digest(manifest)})
        mlflow.set_tags({'execution':'actual local CPU training','dataset':'authored synthetic user-return fixture'})
        commands=[['workflow.py','prepare','--out','outputs/cohort.json'],
                  ['workflow.py','train','--cohort','outputs/cohort.json','--out','outputs/candidate.json'],
                  ['workflow.py','evaluate','--cohort','outputs/cohort.json','--model','outputs/candidate.json','--out','outputs/validation.json']]
        try:
            if fail_before_training:raise ValueError('deliberate pre-training failure')
            if prepared_cohort is not None:
                supplied=w.cohort(prepared_cohort)
                if supplied!=w.prepare(folder/'workspace/scenario.json'):
                    raise ValueError('supplied cohort differs from selected source')
                w.save(folder/'workspace/outputs/cohort.json',supplied)
                commands=commands[1:]
            for index,argv in enumerate(commands):
                completed=subprocess.run([sys.executable,*argv],cwd=folder/'workspace',text=True,capture_output=True,timeout=30)
                (folder/f'command-{index}.stdout.txt').write_text(completed.stdout)
                (folder/f'command-{index}.stderr.txt').write_text(completed.stderr)
                if completed.returncode:raise ValueError('trainer command failed: '+str(index))
            output=folder/'workspace/outputs';model=w.load_model(output/'candidate.json')
            validation=w.strict_json(output/'validation.json')
            if model['cohort_sha256']!=w.sha(output/'cohort.json'):raise ValueError('trained model cohort binding differs')
            mlflow.log_metrics({'validation_accuracy':validation['accuracy'],'validation_correct':validation['correct'],
                                'validation_rows':validation['rows'],'majority_correct':validation['majority_correct']})
            mlflow.log_artifact(str(output/'candidate.json'),'model')
            mlflow.log_artifact(str(folder/'workspace/contract.json'),'model')
            mlflow.log_artifact(str(output/'validation.json'),'evaluation')
            mlflow.log_artifact(str(folder/'runtime.json'),'recipe')
            mlflow.log_artifact(str(Path(__file__)),'recipe')
            summary={'run_id':run_id,'status':'FINISHED','model_sha256':w.sha(output/'candidate.json'),
                     'model_artifact':'model/candidate.json','evaluation_artifact':'evaluation/validation.json',
                     'contract_id':f.digest(manifest),'validation_accuracy':validation['accuracy'],
                     'training_rows':model['training_rows'],'final_test_used':False}
        except Exception as error:
            mlflow.log_artifact(str(folder/'runtime.json'),'recipe')
            mlflow.set_tag('failure_reason',str(error))
            w.save(folder/'failure.json',{'reason':str(error),'model_artifact':None})
            mlflow.log_artifact(str(folder/'failure.json'),'failure')
            raise
    actual=c.get_run(run_id)
    if actual.info.status!='FINISHED':raise ValueError('MLflow run did not finish')
    w.save(folder/'summary.json',summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=w.HERE/'scenario.json');p.add_argument('--workspace',type=Path,default=Path('work/tracking'));p.add_argument('--fail-before-training',action='store_true');p.add_argument('--out',type=Path)
    a=p.parse_args()
    try:
        r=execute(a.source,a.workspace,a.fail_before_training)
        if a.out:w.save(a.out,r)
        print(json.dumps(r,indent=2))
    except (OSError,ValueError,subprocess.TimeoutExpired) as error:p.exit(2,str(error)+'\n')


if __name__=='__main__':main()
