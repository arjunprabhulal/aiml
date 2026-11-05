"""Independent source/answer/trajectory checks. Labels never select agent actions."""
import re


def grade(case, result):
    read_ids = {row['result']['source_id'] for row in result['observations'] if row['tool'] == 'read'}
    expected = set(case['sources'])
    retrieval = expected <= read_ids if expected else None
    cited = {row['source_id'] for row in result['citations']}
    if expected:
        answer = (result['status'] == 'answered' and expected <= cited and
                  all(re.search(p, result['answer'], re.I) for p in case['answer_patterns']) and
                  not any(re.search(p, result['answer'], re.I) for p in case['forbidden_patterns']))
    else:
        # Only an explicit model abstention passes this fixture, never exhaustion.
        answer = result['status'] == 'incomplete' and result['reason'] == 'model_stopped'
    queries = [row['arguments']['query'] for row in result['observations'] if row['tool'] == 'search']
    return {'retrieval_targets_read': retrieval, 'answer_fixture_check': bool(answer),
            'outcome': 'pass' if answer else ('incomplete' if result['status'] == 'incomplete' else 'fail'),
            'trajectory': {'queries': queries, 'refined': len(queries) > 1,
                           'within_limits': all(result['usage'][k] <= result['limits'][k] for k in result['usage'])},
            'scope': 'Source targets, answer patterns and explicit abstention on authored fixtures; human semantic review is separate.'}
