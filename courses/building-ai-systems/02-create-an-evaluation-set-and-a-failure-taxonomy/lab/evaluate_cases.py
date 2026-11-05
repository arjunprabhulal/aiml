"""Apply the existing evaluation runner and summarize first failing boundaries."""
import argparse
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
import harness
from systems import ContractSystem

ROOT = Path(__file__).resolve().parent
FAULTS = ('none', 'source', 'permission', 'approval', 'format', 'no_output')
BOUNDARIES = {'output-contract': 'response-contract', 'source-binding': 'source-selection',
              'task-result': 'task-result', 'action-policy': 'action-policy'}


def boundary(row, case):
    if row['verdict'] == 'pass':
        return 'pass'
    if row['verdict'] == 'incomplete':
        return 'dependency-or-no-output'
    if row['check'] == 'rejection':
        return case['class']
    return BOUNDARIES[row['check']]


def record():
    task = harness.load_task('task')
    cases = harness.load_cases(ROOT / 'cases.json', task)
    task.validate_inputs(cases)
    by_id = {case['id']: case for case in cases['cases']}
    reports = {}
    for fault in FAULTS:
        report = harness.run(ContractSystem(fault), cases, task)
        report['boundary_counts'] = dict(sorted(Counter(boundary(row, by_id[row['case_id']]) for row in report['results']).items()))
        report['first_failures'] = [{'case_id': row['case_id'], 'verdict': row['verdict'],
                                    'boundary': boundary(row, by_id[row['case_id']]), 'reason': row['reason']}
                                   for row in report['results'] if row['verdict'] != 'pass']
        slices = {}
        for field in ('version', 'environment', 'role', 'operation'):
            groups = {}
            for row in report['results']:
                request = by_id[row['case_id']]['input']['request']
                value = request.get(field, 'reader' if field == 'role' else '')
                counts = groups.setdefault(value, {'pass': 0, 'fail': 0, 'incomplete': 0})
                counts[row['verdict']] += 1
            slices[field] = dict(sorted(groups.items()))
        report['slices'] = slices
        reports[fault] = report
    identities = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                  for name in ('architecture.py', 'pages.json', 'systems.py', 'task.py', 'evaluate_cases.py', 'vendor/harness.py')}
    return {'mode': 'fresh local function execution with authored single-fault probes; no model',
            'application_files': identities, 'reports': reports}


def stable_result(result):
    """Ignore run descriptions in their known locations, preserving request slices."""
    stable = copy.deepcopy(result)
    for report in stable['reports'].values():
        for field in ('started_at', 'environment'):
            report['manifest'].pop(field, None)
        for row in report['results']:
            row.pop('latency_s', None)
    return stable


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--save', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = record()
    if args.check and stable_result(result) != stable_result(json.loads((ROOT / 'result.json').read_text())):
        raise SystemExit('case outcomes or version bindings differ from the bundled record')
    if args.save:
        args.save.write_text(json.dumps(result, indent=2) + '\n')
    print('12 authored development cases; local Python function, no model or judge')
    for fault, report in result['reports'].items():
        summary = report['summary']['development']
        print(f"{fault}: pass={summary['pass']}; fail={summary['fail']}; incomplete={summary['incomplete']}")
        for failure in report['first_failures']:
            print(f"  {failure['case_id']}: {failure['boundary']}")
    print('Boundary tags identify the first failed check, not an automatically proven root cause.')


if __name__ == '__main__':
    main()
