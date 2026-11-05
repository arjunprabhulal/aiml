"""Record deliberate split defects on the existing tracker issues, without a model."""
import json
from pathlib import Path
from split_models import SplitDataset,freeze
from tracker_leakcheck import assign_groups,check
from perturb import shouting
ROOT=Path(__file__).parent

def main(check_only=False):
    source=json.loads((ROOT/'tracker-dataset.json').read_text())
    cases=source['cases']
    # Reuse the earlier meaning-preserving perturbation, keeping known source IDs.
    variants=[dict(c,id=c['id']+'-shouting',issue=shouting(c['issue']),source_id=c['id']) for c in cases[:2]]
    dataset=SplitDataset(name=source['name'],version=source['version'],cases=assign_groups(cases+variants))
    locked=freeze(dataset)
    rows=[{'scenario':'grouped split',**check(dataset,locked=locked)}]
    parent=next(c for c in dataset.cases if c.source_id is None and c.split=='held_out')
    crossed=dataset.model_copy(deep=True)
    crossed.cases.append(type(parent)(**dict(parent.model_dump(),id=parent.id+'-derived',source_id=parent.id,split='development')))
    rows.append({'scenario':'variant moved across split',**check(crossed,locked=locked)})
    edited=dataset.model_copy(deep=True)
    target=next(c for c in edited.cases if c.id==parent.id)
    target.expected.label='feature' if target.expected.label!='feature' else 'bug'
    rows.append({'scenario':'held-out label edited',**check(edited,locked=locked)})
    rows.append({'scenario':'prompt contains held-out wording',**check(dataset,prompt='Examples:\n'+parent.issue,locked=locked)})
    for file,value in [('tracker-splits.json',dataset.model_dump()),('tracker-heldout.lock.json',locked.model_dump()),('tracker-split-run.json',{'source_dataset':'tracker-dataset.json','group_seed':7,'near_duplicate_threshold':0.6,'copied_words':8,'scenarios':rows})]:
        text=json.dumps(value,indent=2,ensure_ascii=False)+'\n'
        if check_only:
            if (ROOT/file).read_text()!=text:raise ValueError(file+' differs from a fresh run')
        else:(ROOT/file).write_text(text)
    for row in rows:print(f"{row['scenario']}: {row['decision']} ({len(row['findings'])} findings)")
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true')
    main(parser.parse_args().check)
