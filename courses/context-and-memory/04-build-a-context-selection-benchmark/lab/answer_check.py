"""Send each strategy's held-out requests to the pinned Gemma 4 E2B model and grade the answers.

    python answer_check.py record   # needs Ollama with gemma4:e2b and the pinned tokenizer
    python answer_check.py          # offline: grades the recorded answers again

Only the six held-out cases are sent: the development cases shaped the
strategies, so answers on them would say less. Each case and strategy is
sent with five seeds. answer-keys.json, written from the cases' required
and stale facts before any answer was recorded, defines the grade:

incomplete  no answer to grade
fail        a required fact is missing, or a replaced decision is presented as current
pass        every required fact, and no replaced decision presented as current

An answer that says a fact is missing is still a fail, but it is counted
separately: saying "not in the conversation" is better than guessing.
120 answers from a small model illustrate how the strategies behave; they
are not a measure of answer quality.
"""
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).parent
KEYS = json.loads((HERE / 'answer-keys.json').read_text())['keys']
SENTENCE = re.compile(r'(?<=[.!?])\s+|\n+')
REPLACED = re.compile(r'replac|instead|not |no longer|switch|changed|actually|previous|originally|earlier', re.I)
SAYS_MISSING = re.compile(r"(do not|don't|does not|doesn't) (have|say|mention|state|specify|contain)|not (mention|state|specif|provide|includ|contain)|no information|not enough information|missing|not in the conversation|cannot (find|determine)|provide (more |the )?(context|conversation)",
                          re.I)


def stale_as_current(case_id: str, text: str) -> bool:
    for pattern in KEYS[case_id]['stale']:
        for sentence in SENTENCE.split(text):
            if re.search(pattern, sentence, re.I) and not REPLACED.search(sentence) \
                    and not any(re.search(m, sentence, re.I) for m in KEYS[case_id]['must']):
                return True
    return False


def grade(case_id: str, answer: dict) -> tuple[str, str]:
    text = answer['answer']
    if not text.strip():
        return 'incomplete', 'no answer'
    if stale_as_current(case_id, text):
        return 'fail', 'presents a replaced decision as current'
    missing = [m for m in KEYS[case_id]['must'] if not re.search(m, text, re.I)]
    if missing:
        return 'fail', 'says the fact is missing' if SAYS_MISSING.search(text) else 'required fact absent'
    return 'pass', 'every required fact'


def summarize(recorded: dict) -> dict:
    out = {}
    for strategy, cases in recorded['answers'].items():
        verdicts = [grade(case_id, a) for case_id, answers in cases.items() for a in answers]
        out[strategy] = {**{v: [g[0] for g in verdicts].count(v) for v in ('pass', 'fail', 'incomplete')},
                         'said_missing': sum(g[1] == 'says the fact is missing' for g in verdicts),
                         'stale_as_current': sum(g[1] == 'presents a replaced decision as current' for g in verdicts),
                         'cases_passed_every_trial': sum(all(grade(c, a)[0] == 'pass' for a in answers)
                                                         for c, answers in cases.items())}
    return out


def record() -> dict:
    from answer_model import MODEL, AnswerModel
    from evaluate import load_cases
    from strategies import STRATEGIES
    from tokenizer import count_request
    cases = [c for c in load_cases(HERE / 'cases.json') if c['split'] == 'held_out']
    model = AnswerModel()
    answers = {}
    for name, strategy in STRATEGIES.items():
        answers[name] = {}
        for case in cases:
            messages = strategy(case, count_request)['messages']
            answers[name][case['id']] = [model.answer(messages, [], num_ctx=case['budget']['context_limit'],
                                                      num_predict=case['budget']['max_new_tokens'], seed=seed)
                                         for seed in MODEL['seeds']]
    return {'model': MODEL, 'answers': answers}


if __name__ == '__main__':
    if sys.argv[1:] == ['record']:
        (HERE / 'answer-result.json').write_text(json.dumps(record(), indent=1, ensure_ascii=False) + '\n')
    recorded = json.loads((HERE / 'answer-result.json').read_text())
    graded = {s: {c: [grade(c, a)[0] for a in answers] for c, answers in cases.items()}
              for s, cases in recorded['answers'].items()}
    print(json.dumps({'summary': summarize(recorded), 'graded': graded}, indent=2))
