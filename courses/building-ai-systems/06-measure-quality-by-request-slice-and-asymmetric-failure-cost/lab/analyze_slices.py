"""Analyze saved local outcomes by request slice and declared error cost."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from vendor import harness, task

HERE = Path(__file__).resolve().parent
BOUNDARIES = {'response-contract','source-selection','task-result','action-policy','authorization','input-contract'}
REQUEST_FIELDS = {'version','environment','role','operation'}
INPUTS = ('cases.json','saved-report.json','vendor/task.py','vendor/harness.py')


def validate_policy(policy):
    if (not isinstance(policy,dict) or set(policy) != {'id','unit','cost_by_boundary','incomplete_interval','slices'}
            or not all(isinstance(policy[k],str) and policy[k] for k in ('id','unit'))):
        raise ValueError('invalid cost policy fields')
    costs = policy['cost_by_boundary']
    if not isinstance(costs,dict) or set(costs) != BOUNDARIES:
        raise ValueError('cost policy must cover every known failure boundary')
    if any(type(x) not in (int,float) or not math.isfinite(x) or x < 0 for x in costs.values()):
        raise ValueError('costs must be finite nonnegative numbers')
    interval = policy['incomplete_interval']
    if (not isinstance(interval,list) or len(interval) != 2
            or any(type(x) not in (int,float) or not math.isfinite(x) for x in interval)
            or interval[0] != 0 or interval[1] < max(costs.values())):
        raise ValueError('incomplete interval must span zero through every declared penalty')
    if not isinstance(policy['slices'],list) or not policy['slices']:
        raise ValueError('define at least one request slice')
    ids = set()
    for spec in policy['slices']:
        if (not isinstance(spec,dict) or set(spec) != {'id','where'} or not isinstance(spec['id'],str)
                or not spec['id'] or spec['id'] in ids or not isinstance(spec['where'],dict)
                or not set(spec['where']) <= REQUEST_FIELDS
                or not all(isinstance(v,str) and v for v in spec['where'].values())):
            raise ValueError('invalid or duplicate slice definition')
        ids.add(spec['id'])
    return policy


def ledger(cases, report, policy):
    if report['manifest']['case_set']['sha256'] != cases['sha256']:
        raise ValueError('report and reference case-set identities differ')
    expected = {case['id']:case for case in cases['cases']}
    failures = {}
    for row in report['first_failures']:
        id = row['case_id']
        if id not in expected or id in failures:
            raise ValueError('unknown or duplicate failure tag')
        failures[id] = row
    received = {}
    for row in report['results']:
        id = row['case_id']
        if id not in expected or id in received or row['trial'] != 0:
            raise ValueError('one trial-zero result is required for each known case')
        case = expected[id]
        if row['split'] != case['split'] or row['class'] != case['class']:
            raise ValueError('result metadata differs from the reference case')
        verdict = row['verdict']
        if verdict not in ('pass','fail','incomplete'):
            raise ValueError('unknown verdict')
        tag = failures.get(id)
        if verdict == 'pass':
            if tag is not None:
                raise ValueError('passing case cannot have a failure tag')
            boundary, cost = 'pass', 0
        else:
            if tag is None or tag['verdict'] != verdict or tag['reason'] != row['reason']:
                raise ValueError('failure tag differs from its result')
            boundary = tag['boundary']
            if verdict == 'incomplete':
                if boundary != 'dependency-or-no-output':
                    raise ValueError('unknown incomplete boundary')
                cost = None
            else:
                if boundary not in policy['cost_by_boundary']:
                    raise ValueError('failure has no declared penalty')
                cost = policy['cost_by_boundary'][boundary]
        request = case['input']['request']
        received[id] = {'id':id, 'verdict':verdict, 'boundary':boundary, 'cost':cost,
                        'request':{field:request.get(field,'reader' if field=='role' else '')
                                   for field in sorted(REQUEST_FIELDS)}}
    if set(received) != set(expected):
        raise ValueError('missing result: keep incomplete execution as an explicit row')
    return [received[case['id']] for case in cases['cases']]


def summarize(rows, policy):
    n = len(rows)
    counts = {name:sum(row['verdict']==name for row in rows) for name in ('pass','fail','incomplete')}
    known = math.fsum(row['cost'] for row in rows if row['cost'] is not None)
    missing = counts['incomplete']
    return {'cases':n, **counts,
            'pass_fraction':counts['pass']/n if n else None,
            'completion_fraction':(n-missing)/n if n else None,
            'known_cost':known if n else None,
            'total_cost':known if n and not missing else None,
            'cost_interval':[known+missing*bound for bound in policy['incomplete_interval']] if n else None,
            'cost_per_case':known/n if n and not missing else None}


def analyze(cases, report, policy):
    validate_policy(policy)
    rows = ledger(cases,report,policy)
    slices = {}
    for spec in policy['slices']:
        members = [row for row in rows if all(row['request'][key]==value for key,value in spec['where'].items())]
        slices[spec['id']] = {'where':spec['where'], 'case_ids':[row['id'] for row in members], **summarize(members,policy)}
    return {'overall':summarize(rows,policy), 'slices':slices, 'ledger':rows}


def record(root=HERE):
    root = Path(root)
    manifest = json.loads((root/'input-manifest.json').read_text())
    if set(manifest['sha256']) != set(INPUTS):
        raise ValueError('input identity inventory differs')
    for name,expected in manifest['sha256'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise ValueError('reviewed input bytes differ: '+name)
    cases = harness.load_cases(root/'cases.json', task)
    task.validate_inputs(cases)
    saved = json.loads((root/'saved-report.json').read_text())
    policy = json.loads((root/'cost-policy.json').read_text())
    reports = {}
    for name, report in saved['reports'].items():
        if (report['manifest']['harness_sha256'] != manifest['sha256']['vendor/harness.py']
                or report['manifest']['task']['sha256'] != manifest['sha256']['vendor/task.py']):
            raise ValueError('saved evaluator identity differs')
        reports[name] = analyze(cases,report,policy)
    return {'mode':'saved local-function evaluation outcomes; scenario cost analysis only',
            'cost_policy':policy, 'case_set_sha256':cases['sha256'], 'reports':reports,
            'files':{name:hashlib.sha256((root/name).read_bytes()).hexdigest()
                     for name in (*INPUTS,'input-manifest.json','cost-policy.json','analyze_slices.py')}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');parser.add_argument('--save',type=Path)
    args=parser.parse_args();result=record()
    if args.check and result != json.loads((HERE/'result.json').read_text()):
        raise SystemExit('slice/cost results or input bindings differ')
    if args.save:
        with args.save.open('x') as file:file.write(json.dumps(result,indent=2)+'\n')
    print('Saved local-function outcomes; declared scenario penalty points, not observed money')
    for name, report in result['reports'].items():
        row=report['overall']
        cost=str(row['total_cost']) if row['total_cost'] is not None else 'unknown '+str(row['cost_interval'])
        print(f"{name}: pass={row['pass']}/{row['cases']}; complete={row['cases']-row['incomplete']}/{row['cases']}; cost={cost}")
    critical=result['reports']['permission']['slices']['reader-production-proposal']
    print(f"permission / reader production proposals: pass={critical['pass']}/{critical['cases']}; cost={critical['total_cost']:g}")
    print('Version 4 slice: empty, not a passing group')
    print('Slices overlap; totals are not additive. Unknown-cost ranges are policy bounds, not confidence intervals.')


if __name__=='__main__':main()
