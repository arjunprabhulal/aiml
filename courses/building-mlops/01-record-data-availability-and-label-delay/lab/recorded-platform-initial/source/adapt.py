"""Run the shared application's data and reproducibility workshops."""
import argparse,copy,json
from pathlib import Path
import workflow as w
import foundations as f


def run(topic, source, root, cohort, model):
    root=Path(root)
    if topic=='splits':return f.split_report(source)
    if topic=='availability':return f.availability_report(source)
    if topic=='costs':return f.cost_report(cohort,model)
    if topic=='validation':
        root.mkdir(parents=True,exist_ok=True)
        return {'clean_batch':f.validate_source(source,root/'accepted-batch'),
                'deliberately_invalid_batch':f.validate_source(source,root/'blocked-batch',True)}
    if topic=='history':
        root.mkdir(parents=True,exist_ok=True);database=root/'features.sqlite'
        return {'initial_materialization':f.publish_history(source,database),
                'late_correction':f.history_report(source,database)}
    if topic=='parity':return f.parity_report(source,root/'features.sqlite')
    if topic=='versioning':
        root.mkdir(parents=True,exist_ok=True);manifest=f.contract(source)
        bound=f.bind_contract(root/'identities.sqlite',manifest)
        conflict=copy.deepcopy(manifest);conflict['feature']['window_seconds']=172800
        try:f.bind_contract(root/'identities.sqlite',conflict)
        except ValueError as error:blocked=str(error)
        else:raise AssertionError('changed feature must not retain version 1')
        w.save(root/'application-contract.json',manifest)
        return {'bound':bound,'changed_definition_refused':blocked,
                'identical_retry_id':f.bind_contract(root/'identities.sqlite',manifest)['contract_id']}
    raise ValueError('unknown topic')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('topic',choices=['splits','availability','costs','validation','history','parity','versioning'])
    p.add_argument('--source',type=Path,default=w.HERE/'scenario.json')
    p.add_argument('--work',type=Path,default=Path('work/adaptations'))
    p.add_argument('--cohort',type=Path,default=Path('work/cohort.json'))
    p.add_argument('--model',type=Path,default=Path('work/candidate.json'))
    p.add_argument('--out',type=Path)
    a=p.parse_args()
    try:
        value=run(a.topic,a.source,a.work,a.cohort,a.model)
        if a.out:w.save(a.out,value)
        print(json.dumps(value,indent=2,allow_nan=False))
    except (OSError,ValueError,KeyError) as error:p.exit(2,str(error)+'\n')


if __name__=='__main__':main()
