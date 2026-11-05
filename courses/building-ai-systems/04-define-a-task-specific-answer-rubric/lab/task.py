"""Adapter for the unchanged runner: grade completed rubric decisions only."""
NAME, VERSION = 'docuctl-explanation-rubric', '1'
OUTPUT_FIELDS = {'answer_id':str,'acceptable':bool}


def validate_expected(expected):
    if set(expected) != {'acceptable','source_sha256','rubric_sha256','review_sha256'} or expected['acceptable'] is not True:
        raise ValueError('case must require rubric acceptance and all revision bindings')
    for name in ('source_sha256','rubric_sha256','review_sha256'):
        if not isinstance(expected[name],str) or len(expected[name])!=64 or any(c not in '0123456789abcdef' for c in expected[name]):
            raise ValueError('expected revision must be a SHA-256 digest')


def decision_contract(case, output):
    return (isinstance(output,dict) and set(output)==set(OUTPUT_FIELDS)
            and type(output['answer_id']) is str and type(output['acceptable']) is bool
            and output['answer_id']==case['id'], 'invalid or misassigned rubric decision')


def rubric_acceptance(case, output):
    return output['acceptable'] is True, 'one or more required rubric criteria did not meet'


GRADERS=({'name':'decision-contract','version':VERSION,'kind':'contract','check':decision_contract},
         {'name':'rubric-acceptance','version':VERSION,'kind':'outcome','check':rubric_acceptance})
