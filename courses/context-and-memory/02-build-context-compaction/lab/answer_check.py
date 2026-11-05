"""Send the compacted request and the drop-oldest baseline to the pinned Gemma 4 E2B model.

    python answer_check.py record   # needs Ollama with gemma4:e2b; writes answer-result.json
    python answer_check.py          # offline: grades the recorded answers again

The question asks which decisions still apply to the database and the
exports. The compacted request carries notes from removed turns, including
the replaced "we will use MySQL" decision and the later PostgreSQL one.
Each answer is graded:

incomplete  no answer to grade: empty, or a tool call instead of an answer
fail        presents MySQL as the current database, or leaves out PostgreSQL
            or the 15-minute export limit
pass        names PostgreSQL and the 15-minute export limit, and mentions
            MySQL only as replaced

Ten answers from a small model illustrate how the two requests behave; they
are not a measure of answer quality. The rules are string checks, so the
article shows every recorded answer.
"""
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).parent
SENTENCE = re.compile(r'(?<=[.!?])\s+|\n+')
REPLACED = re.compile(r'replac|instead|no longer|switch|previously|originally|changed|supersed|not use',
                      re.IGNORECASE)
EXPORT_LIMIT = re.compile(r'15[- ]minute|15 minutes|fifteen minutes', re.IGNORECASE)


def requests() -> dict:
    run = json.loads((HERE / 'compaction-result.json').read_text())
    return {'compacted': run['compacted']['messages'], 'drop oldest': run['drop_oldest']['messages']}


def stale_mysql(text: str) -> int:
    """Sentences that name MySQL as if it still applied."""
    return sum(1 for s in SENTENCE.split(text)
               if 'mysql' in s.lower() and 'postgres' not in s.lower() and not REPLACED.search(s))


def grade(answer: dict) -> tuple[str, str]:
    text = answer['answer']
    if not text.strip():
        return 'incomplete', 'asked for a tool call instead of answering' if answer['tool_calls'] else 'empty answer'
    if stale_mysql(text):
        return 'fail', 'presents MySQL as current'
    missing = [name for name, found in (('PostgreSQL', 'postgres' in text.lower()),
                                        ('15-minute export limit', bool(EXPORT_LIMIT.search(text)))) if not found]
    if missing:
        return 'fail', 'leaves out ' + ' and '.join(missing)
    return 'pass', 'both decisions, no stale MySQL'


def summarize(recorded: dict) -> dict:
    out = {}
    for name, answers in recorded['answers'].items():
        verdicts = [grade(a) for a in answers]
        out[name] = {**{v: [g[0] for g in verdicts].count(v) for v in ('pass', 'fail', 'incomplete')},
                     'presents_mysql_as_current': sum(stale_mysql(a['answer']) > 0 for a in answers),
                     'names_postgresql': sum('postgres' in a['answer'].lower() for a in answers),
                     'names_export_limit': sum(bool(EXPORT_LIMIT.search(a['answer'])) for a in answers)}
    return out


def record() -> dict:
    from answer_model import MODEL, AnswerModel
    run = json.loads((HERE / 'compaction-result.json').read_text())
    request = json.loads((HERE / 'request.json').read_text())
    model = AnswerModel()
    answers = {name: [model.answer(messages, [], num_ctx=request['context_limit'],
                                   num_predict=request['max_new_tokens'], seed=seed) for seed in MODEL['seeds']]
               for name, messages in requests().items()}
    return {'model': MODEL, 'answers': answers}


if __name__ == '__main__':
    if sys.argv[1:] == ['record']:
        (HERE / 'answer-result.json').write_text(json.dumps(record(), indent=1, ensure_ascii=False) + '\n')
    recorded = json.loads((HERE / 'answer-result.json').read_text())
    run = json.loads((HERE / 'compaction-result.json').read_text())
    graded = {name: [{'seed': a['seed'], 'verdict': grade(a)[0], 'reason': grade(a)[1]} for a in answers]
              for name, answers in recorded['answers'].items()}
    prompt_tokens = {name: {'pinned_template': run['compacted' if name == 'compacted' else 'drop_oldest']['input_tokens'],
                            'ollama_prompt_eval_count': sorted({a['prompt_tokens'] for a in answers})}
                     for name, answers in recorded['answers'].items()}
    print(json.dumps({'summary': summarize(recorded), 'prompt_tokens': prompt_tokens, 'graded': graded}, indent=2))
