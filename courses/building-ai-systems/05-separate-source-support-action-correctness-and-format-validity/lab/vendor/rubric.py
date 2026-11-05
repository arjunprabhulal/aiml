"""Validate authored judgement bindings and apply a task-specific decision rule.

No semantic judgement is inferred from text. A quote match checks provenance,
not entailment. Uncertain/missing judgements need review before a quality verdict.
"""
import hashlib
import json

RATINGS = {'meets', 'does_not_meet', 'uncertain'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def validate_rubric(rubric, source):
    if (not isinstance(rubric,dict) or set(rubric) != {'id','version','task','acceptance','ratings','criteria'}
            or type(rubric['version']) is not int or rubric['version'] < 1
            or not all(isinstance(rubric[key],str) and rubric[key] for key in ('id','task','acceptance'))
            or not isinstance(rubric['ratings'],list) or not all(isinstance(x,str) for x in rubric['ratings'])
            or set(rubric['ratings']) != RATINGS or not isinstance(rubric['criteria'],list)
            or not rubric['criteria']):
        raise ValueError('invalid rubric contract')
    seen={}
    for criterion in rubric['criteria']:
        if (not isinstance(criterion,dict) or set(criterion) != {'id','rule','reference_quote'} or not all(isinstance(criterion[key],str) and criterion[key] for key in ('id','rule','reference_quote'))
                or criterion['id'] in seen
                or not criterion['reference_quote'] or criterion['reference_quote'] not in source):
            raise ValueError('invalid criterion or reference quote')
        seen[criterion['id']]=criterion
    return seen


def assess(case, review, criteria, source, source_sha256, rubric_sha256):
    answer=case['input']['answer']
    if (set(answer) != {'text','citation'} or not all(isinstance(v,str) and v for v in answer.values())):
        raise ValueError('answer needs nonempty text and citation')
    expected=case['expected']
    if expected['source_sha256'] != source_sha256 or expected['rubric_sha256'] != rubric_sha256:
        raise ValueError('case uses a different source or rubric version')
    if expected['review_sha256'] != fingerprint(review):
        raise ValueError('case uses a different judgement revision')
    if review is None:
        return {'status':'pending','reason':'no authored review fixture','ratings':{}}
    if (set(review) != {'answer_id','answer_sha256','source_sha256','rubric_sha256','judgements'}
            or review['answer_id'] != case['id'] or review['answer_sha256'] != fingerprint(answer)
            or review['source_sha256'] != source_sha256 or review['rubric_sha256'] != rubric_sha256):
        raise ValueError('judgement is bound to different answer/source/rubric content')
    judgements=review['judgements']
    if not isinstance(judgements,dict) or not set(judgements) <= set(criteria):
        raise ValueError('unknown criterion in judgement')
    for criterion, judgement in judgements.items():
        if (not isinstance(judgement,dict) or set(judgement) != {'rating','reason','reference_quote','answer_span'}
                or not isinstance(judgement['rating'],str) or judgement['rating'] not in RATINGS
                or not isinstance(judgement['reason'],str) or not judgement['reason']
                or not isinstance(judgement['reference_quote'],str) or not judgement['reference_quote']
                or judgement['reference_quote'] != criteria[criterion]['reference_quote']
                or not isinstance(judgement['answer_span'],str)
                or judgement['answer_span'] not in answer['text']):
            raise ValueError('invalid judgement rating, reason or bound excerpt')
    ratings={key:value['rating'] for key,value in judgements.items()}
    if set(judgements) != set(criteria) or 'uncertain' in ratings.values():
        return {'status':'pending','reason':'missing or uncertain criterion judgement','ratings':ratings}
    failed=[key for key,value in ratings.items() if value=='does_not_meet']
    return {'status':'rejected' if failed else 'accepted','reason':', '.join(failed),'ratings':ratings}
