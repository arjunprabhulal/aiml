"""Apply the existing runner to completed authored rubric judgements, not models."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from vendor import harness
import task
from rubric import validate_rubric, assess

ROOT=Path(__file__).resolve().parent


def load(root=ROOT):
    root=Path(root)
    rubric_raw=(root/'rubric.json').read_bytes();source_raw=(root/'source.txt').read_bytes()
    rubric=json.loads(rubric_raw);source=source_raw.decode()
    criteria=validate_rubric(rubric,source)
    cases=harness.load_cases(root/'cases.json',harness.load_task('task'))
    for case in cases['cases']:
        if (not isinstance(case['input'],dict) or set(case['input'])!={'question','answer'}
                or case['input']['question']!=rubric['task']):
            raise ValueError('case question does not match the rubric task')
    annotations=json.loads((root/'annotations.json').read_text())
    reviews={}
    ids={case['id'] for case in cases['cases']}
    for review in annotations['reviews']:
        id=review['answer_id']
        if id not in ids or id in reviews:raise ValueError('unknown or duplicate review identity')
        reviews[id]=review
    decisions={case['id']:assess(case,reviews.get(case['id']),criteria,source,
                   hashlib.sha256(source_raw).hexdigest(),hashlib.sha256(rubric_raw).hexdigest())
               for case in cases['cases']}
    return cases,decisions


class FixtureJudgements:
    name='authored-rubric-adapter';version='1';mode='authored_annotation_fixture'
    model=prompt=tools=None

    def __init__(self,decisions):self.decisions=decisions

    def respond(self,case,trial):
        decision=self.decisions[case['id']]
        if decision['status']=='pending':raise ValueError('pending review must not enter the scored subset')
        return harness.Answer({'answer_id':case['id'],'acceptable':decision['status']=='accepted'},
                              {'origin':'authored judgement fixture','ratings':decision['ratings'],
                               'answer':case['input']['answer'],'reason':decision['reason']})


def record(root=ROOT):
    full,decisions=load(root)
    selected=[case for case in full['cases'] if decisions[case['id']]['status']!='pending']
    report=None
    if selected:
        subset={'name':full['name']+'-completed-judgements','task':full['task'],'cases':selected}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cases.json';path.write_text(json.dumps(subset))
            cases=harness.load_cases(path,harness.load_task('task'))
            report=harness.run(FixtureJudgements(decisions),cases,task)
    pending=[{'id':id,'reason':row['reason']} for id,row in decisions.items() if row['status']=='pending']
    return {'mode':'authored answer/judgement fixtures; local decision execution; no model or human study',
            'full_case_set_sha256':full['sha256'], 'coverage':{'candidates':len(full['cases']),
                'graded':len(selected),'pending':len(pending),'pending_cases':pending},
            'decisions':decisions,'report':report,
            'files':{name:hashlib.sha256((Path(root)/name).read_bytes()).hexdigest()
                     for name in ('source.txt','rubric.json','cases.json','annotations.json')}}


def stable_result(result):
    stable=copy.deepcopy(result)
    if stable['report']:
        stable['report']['manifest'].pop('started_at',None)
        stable['report']['manifest'].pop('environment',None)
        for row in stable['report']['results']:row.pop('latency_s',None)
    return stable


def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--save',type=Path)
    args=p.parse_args();result=record()
    if args.check and stable_result(result)!=stable_result(json.loads((ROOT/'result.json').read_text())):
        raise SystemExit('rubric decisions or revision bindings differ from the bundled record')
    if args.save:args.save.write_text(json.dumps(result,indent=2)+'\n')
    coverage=result['coverage'];summary=result['report']['summary']['development'] if result['report'] else {}
    print('Authored answer and judgement fixtures; no model responses or human-rating study')
    print(f"Coverage: {coverage['graded']} graded of {coverage['candidates']} candidates; {coverage['pending']} pending")
    print(f"Completed rubric decisions: accepted={summary.get('pass',0)}; rejected={summary.get('fail',0)}")
    for id,decision in result['decisions'].items():print(f"{id}: {decision['status']}"+(f" ({decision['reason']})" if decision['reason'] else ''))
    print('Pending judgements remain outside the scored subset and visible in coverage.')
    print('Quote matching validates excerpts; semantic ratings are supplied judgements.')


if __name__=='__main__':main()
