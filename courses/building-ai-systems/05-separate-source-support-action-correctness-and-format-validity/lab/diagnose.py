"""Keep format, source and action diagnostics separate; reuse the existing rubric."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from vendor import action_task, rubric

HERE = Path(__file__).resolve().parent
STATUS = {'accepted':'pass', 'rejected':'fail', 'pending':'pending'}
FILES = ('responses.json','expected-action.json','rubric-inputs/cases.json',
         'rubric-inputs/annotations.json','rubric-inputs/rubric.json','rubric-inputs/source.txt',
         'diagnose.py','vendor/action_task.py','vendor/rubric.py')


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON field')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('nonstandard JSON constant')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def load(root=HERE):
    root = Path(root)
    directory = root/'rubric-inputs'
    source_raw = (directory/'source.txt').read_bytes()
    rubric_raw = (directory/'rubric.json').read_bytes()
    source = source_raw.decode()
    criteria = rubric.validate_rubric(strict_json(rubric_raw), source)
    source_sha = hashlib.sha256(source_raw).hexdigest()
    rubric_sha = hashlib.sha256(rubric_raw).hexdigest()
    cases = {case['id']:case for case in strict_json((directory/'cases.json').read_bytes())['cases']}
    reviews = {}
    for review in strict_json((directory/'annotations.json').read_bytes())['reviews']:
        id = review['answer_id']
        if id not in cases or id in reviews:
            raise ValueError('unknown or duplicate authored review')
        reviews[id] = review
    # Validate the original bindings before accepting them as diagnostic inputs.
    decisions = {id:rubric.assess(case, reviews.get(id), criteria, source, source_sha, rubric_sha)
                 for id,case in cases.items()}
    expected = strict_json((root/'expected-action.json').read_bytes())
    action_task.validate_expected(expected)
    if set(expected) != {'architecture','proposed_command','citation','approval_required','executed'}:
        raise ValueError('this exercise expects a structured action proposal')
    if expected['proposed_command'] not in source:
        raise ValueError('expected command does not occur in the supplied guide')
    rows = strict_json((root/'responses.json').read_bytes())['responses']
    ids = set()
    for row in rows:
        if (set(row) != {'id','rubric_case','raw_response'} or not isinstance(row['id'],str)
                or not row['id'] or row['id'] in ids or row['rubric_case'] not in cases
                or not isinstance(row['raw_response'],str)):
            raise ValueError('invalid or duplicate response fixture')
        ids.add(row['id'])
    return {'cases':cases, 'decisions':decisions, 'expected':expected, 'responses':rows}


def parse_response(raw, expected):
    response = strict_json(raw)
    if not isinstance(response, dict) or set(response) != {'answer','proposal'}:
        raise ValueError('response needs exactly answer and proposal')
    answer = response['answer']
    if (not isinstance(answer,dict) or set(answer) != {'text','citation'}
            or not all(type(value) is str and value.strip() for value in answer.values())):
        raise ValueError('answer needs nonempty text and citation strings')
    valid, reason = action_task.output_contract({'expected':expected}, response['proposal'])
    if not valid:
        raise ValueError(reason)
    return response


def diagnose(row, context):
    try:
        response = parse_response(row['raw_response'], context['expected'])
    except (ValueError, TypeError) as error:
        return {'format':{'status':'fail','reason':str(error)},
                'source':{'status':'not_run'}, 'action':{'status':'not_run'},
                'explanation':{'status':'not_run'}, 'decision':'rejected'}
    case = context['cases'][row['rubric_case']]
    original = context['decisions'][row['rubric_case']]
    bound = response['answer'] == case['input']['answer']
    rating = original['ratings'].get('support') if bound else None
    semantic = {'meets':'pass','does_not_meet':'fail'}.get(rating,'pending')
    citations = (response['answer']['citation'] == context['expected']['citation']
                 and action_task.source_binding({'expected':context['expected']}, response['proposal'])[0])
    source_status = 'fail' if not citations or semantic == 'fail' else semantic
    action_checks = {name:check({'expected':context['expected']}, response['proposal'])[0]
                     for name,check in (('requested_command',action_task.task_result),
                                        ('unexecuted_approval_bound',action_task.action_policy))}
    action_status = 'pass' if all(action_checks.values()) else 'fail'
    explanation_status = STATUS[original['status']] if bound else 'pending'
    statuses = (source_status, action_status, explanation_status)
    # Preserve unfinished review instead of manufacturing an overall quality grade.
    decision = 'pending' if 'pending' in statuses else 'rejected' if 'fail' in statuses else 'accepted'
    return {'format':{'status':'pass'},
            'source':{'status':source_status,'citations_match':citations,
                      'semantic_review':semantic,'rating':rating,'answer_review_bound':bound},
            'action':{'status':action_status,'checks':action_checks},
            'explanation':{'status':explanation_status,
                           'reason':original['reason'] if bound else 'changed answer needs a new bound review'},
            'decision':decision}


def record(root=HERE):
    context = load(root)
    results = {row['id']:diagnose(row,context) for row in context['responses']}
    counts = {name:sum(row['decision']==name for row in results.values())
              for name in ('accepted','rejected','pending')}
    return {'mode':'authored response/review fixtures; actual local diagnostic execution; no model calls',
            'files':{name:hashlib.sha256((Path(root)/name).read_bytes()).hexdigest() for name in FILES},
            'results':results, 'decisions':counts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--save',type=Path)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    result = record()
    if args.check and result != strict_json((HERE/'result.json').read_bytes()):
        raise SystemExit('diagnostics or source/fixture identities differ')
    if args.save:
        with args.save.open('x') as file:
            file.write(json.dumps(result,indent=2)+'\n')
    print('Authored responses and semantic judgements; local checks, no model calls')
    for id,row in result['results'].items():
        print(id+': '+', '.join(key+'='+row[key]['status'] for key in ('format','source','action','explanation'))+'; '+row['decision'])
    counts = result['decisions']
    print(f"Fixture decisions: {counts['accepted']} accepted; {counts['rejected']} rejected; {counts['pending']} pending")
    print('not_run means blocked by invalid format; pending means review is unfinished.')


if __name__=='__main__': main()
