"""Send the turn-40 and turn-50 requests of every strategy to the pinned Gemma 4 E2B model.

    python answer_check.py record   # needs Ollama with gemma4:e2b and the pinned tokenizer
    python answer_check.py          # offline: grades the recorded answers again

The requests are the ones benchmark.py builds at the default facts quota, sent
unchanged with the conversation's own budget: a 512-token context and at most
128 answer tokens. Each request is sent with five seeds. KEYS, written from the
checkpoints' required, stale and forgotten facts before any answer was recorded.
After reading the first recording, the date patterns were widened to accept
ordinals ("3rd") and the replacement markers were narrowed: "from" and "was"
had let "The trip is planned from 3 to 6 November" pass.

incomplete  no answer to grade
fail        the forgotten passport number appears, a replaced fact is stated as
            current, or a required fact is missing
pass        every required fact, no replaced fact stated as current, and no
            forgotten fact

Forty answers from a small model illustrate how the four requests behave; they
are not a measure of answer quality.
"""
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).parent
CHECKPOINTS = (40, 50)
STRATEGIES = ('recent', 'notes', 'append-only', 'managed')
KEYS = {
    'required': {
        'fish now': r'\bfish\b',
        '180 euros per night': r'\b180\b',
        'going to Porto': r'\bporto\b',
        '10 to 13 November': r'\b10(?:th)?\b[^\n]{0,25}\b13(?:th)?\b',
        'hotel near the river': r'\briver\b',
        'morning flight': r'\bmorning\b',
        'Bob will join': r'\bbob\b',
    },
    'stale': {
        'I am vegetarian.': r'\bvegetarian\b',
        '150 euros per night': r'\b150\b',
        '3 to 6 November': r'\b3(?:rd)?\b[^\n]{0,25}\b6(?:th)?\b',
    },
    'deleted': {'P1234567': r'P1234567'},
}
SENTENCE = re.compile(r'(?<=[.!?])\s+|\n+')
# A sentence that marks the old value as replaced does not state it as current.
REPLACED = re.compile(r"\bnot\b|n't|\bno longer\b|\bprevious(?:ly)?\b|\boriginal(?:ly)?\b|\bearlier\b|\bold\b|"
                      r"\breplaced\b|\binstead of\b|\b(?:changed|moved|raised) from\b", re.I)


def grade(checkpoint: dict, answer: dict) -> tuple[str, str]:
    text = answer['answer']
    if not text.strip():
        return 'incomplete', 'no answer'
    if any(re.search(KEYS['deleted'][f], text) for f in checkpoint['deleted']):
        return 'fail', 'sends the forgotten passport number'
    sentences = SENTENCE.split(text)
    stale = [f for f in checkpoint['stale']
             if any(re.search(KEYS['stale'][f], s, re.I) and not REPLACED.search(s) for s in sentences)]
    if stale:
        return 'fail', 'states a replaced fact as current: ' + ', '.join(stale)
    missing = [f for f in checkpoint['required'] if not re.search(KEYS['required'][f], text, re.I)]
    if missing:
        cut = '; stopped at the answer-token limit' if answer.get('done_reason') == 'length' else ''
        return 'fail', f'missing {len(missing)} of {len(checkpoint["required"])} required facts{cut}'
    return 'pass', 'every required fact'


def facts_found(checkpoint: dict, answer: dict) -> int:
    return sum(bool(re.search(KEYS['required'][f], answer['answer'], re.I)) for f in checkpoint['required'])


def checkpoints() -> dict:
    case = json.loads((HERE / 'conversation.json').read_text())
    return {c['after']: c for c in case['checkpoints'] if c['after'] in CHECKPOINTS}


def summarize(recorded: dict) -> dict:
    out = {}
    for name, answers in recorded['answers'].items():
        checkpoint = checkpoints()[recorded['checkpoints'][name]]
        verdicts = [grade(checkpoint, a) for a in answers]
        out[name] = {v: [g[0] for g in verdicts].count(v) for v in ('pass', 'fail', 'incomplete')}
        out[name]['facts_in_answers'] = f'{sum(facts_found(checkpoint, a) for a in answers)} of {len(checkpoint["required"]) * len(answers)}'
        reasons = [g[1] for g in verdicts if g[0] != 'pass']
        out[name]['reasons'] = {r: reasons.count(r) for r in sorted(set(reasons))}
    return out


def record() -> dict:
    from answer_model import MODEL, AnswerModel
    from benchmark import run
    case = json.loads((HERE / 'conversation.json').read_text())
    requests = {}
    run(case, keep=requests)
    model = AnswerModel()
    budget = case['budget']
    answers, at = {}, {}
    for after in CHECKPOINTS:
        for strategy in STRATEGIES:
            name = f'{strategy} · turn {after}'
            at[name] = after
            answers[name] = [model.answer(requests[strategy, after], [], num_ctx=budget['context_limit'],
                                          num_predict=budget['max_new_tokens'], seed=seed)
                             for seed in MODEL['seeds']]
    return {'model': MODEL, 'checkpoints': at, 'answers': answers}


if __name__ == '__main__':
    if sys.argv[1:] == ['record']:
        (HERE / 'answer-result.json').write_text(json.dumps(record(), indent=1, ensure_ascii=False) + '\n')
    recorded = json.loads((HERE / 'answer-result.json').read_text())
    graded = {name: [grade(checkpoints()[recorded['checkpoints'][name]], a)[0] for a in answers]
              for name, answers in recorded['answers'].items()}
    print(json.dumps({'summary': summarize(recorded), 'graded': graded}, indent=2))
