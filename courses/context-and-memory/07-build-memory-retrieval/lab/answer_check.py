"""Send the per-kind memory block and the pooled baseline to the pinned Gemma 4 E2B model.

    python answer_check.py record   # needs Ollama with gemma4:e2b and the pinned tokenizer
    python answer_check.py          # offline: grades the recorded answers again

Each of the two questions is asked twice: with the block retrieve() builds,
one section per kind, and with the pooled baseline's four memories in the
same format. Each request is sent with five seeds. KEYS, written from the
scenario's required and stale facts before any answer was recorded:

incomplete  no answer to grade
fail        a required fact is missing, or the replaced "vegetarian" fact is stated as current
pass        every required fact, and no replaced fact stated as current

Twenty answers from a small model illustrate how the two blocks behave;
they are not a measure of answer quality.
"""
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).parent
SYSTEM = 'You help Alice with travel. Answer from the memories in the user message; say when something is missing.'
KEYS = {
    'Find a hotel in Porto like the one we booked last time.': {
        'must': {'trip dates': r'\b3\b[^.\n]*\b6\b[^.\n]*nov|nov[^.\n]*\b3\b[^.\n]*\b6\b',
                 'budget': r'\b150\b', 'near a river': r'river'},
        'stale': None},
    'What should Alice eat at the hotel restaurant? Is she vegetarian?': {
        'must': {'eats fish': r'\bfish\b'}, 'stale': r'\bvegetarian\b'},
}
SENTENCE = re.compile(r'(?<=[.!?])\s+|\n+')
NEGATED = re.compile(r"\bnot\b|\bno\b|n't|\bisn't\b|\bno longer\b", re.I)


def blocks() -> dict:
    """{name: (question, user message)} for the per-kind and pooled blocks."""
    from memory import Clock, MemoryStore, Scope
    from retrieval import HEADER, line, retrieve
    import tempfile
    scenario = json.loads((HERE / 'scenario.json').read_text())
    run = json.loads((HERE / 'retrieval-result.json').read_text())
    scope = Scope(*scenario['scope'])
    out = {}
    with tempfile.TemporaryDirectory() as folder:
        clock = Clock()
        store = MemoryStore(str(Path(folder) / 'memory.sqlite3'), clock)
        ids, day = {}, 0
        for item in scenario['memories']:
            clock.advance(days=item['day'] - day)
            day = item['day']
            if 'correct' in item:
                store.correct(scope, ids[item['correct']], item['text'], item['source'])
                continue
            memory_id = store.remember(scope, item['level'], item['text'], item['source'],
                                       kind=item['kind'], occurred_at=item.get('occurred_at'))
            ids[item.get('key', memory_id)] = memory_id
        rows = {row['id']: row for row in store.current(scope)}
        for case, recorded in zip(scenario['queries'], run['results']):
            question = case['query']
            per_kind = retrieve(store, scope, question)['content']
            pooled = '\n'.join([HEADER, '<memories>', *(line(rows[i]) for i in recorded['pooled']['ids']), '</memories>'])
            for name, block in (('per kind', per_kind), ('pooled', pooled)):
                out[f'{name} · {question}'] = (question, f'{block}\n\nQuestion: {question}')
        store.close()
    return out


def grade(question: str, answer: dict) -> tuple[str, str]:
    text = answer['answer']
    if not text.strip():
        return 'incomplete', 'no answer'
    key = KEYS[question]
    if key['stale'] and any(re.search(key['stale'], s, re.I) and not NEGATED.search(s) for s in SENTENCE.split(text)):
        return 'fail', 'states the replaced fact as current'
    missing = [name for name, pattern in key['must'].items() if not re.search(pattern, text, re.I)]
    if missing:
        return 'fail', 'missing: ' + ', '.join(missing)
    return 'pass', 'every required fact'


def summarize(recorded: dict) -> dict:
    out = {}
    for name, answers in recorded['answers'].items():
        question = recorded['questions'][name]
        verdicts = [grade(question, a) for a in answers]
        out[name] = {v: [g[0] for g in verdicts].count(v) for v in ('pass', 'fail', 'incomplete')}
        out[name]['reasons'] = sorted({g[1] for g in verdicts if g[0] != 'pass'})
    return out


def record() -> dict:
    from answer_model import MODEL, AnswerModel
    model = AnswerModel()
    answers, questions = {}, {}
    for name, (question, user) in blocks().items():
        questions[name] = question
        messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]
        answers[name] = [model.answer(messages, [], num_ctx=2048, num_predict=200, seed=seed) for seed in MODEL['seeds']]
    return {'model': MODEL, 'system': SYSTEM, 'questions': questions, 'answers': answers}


if __name__ == '__main__':
    if sys.argv[1:] == ['record']:
        (HERE / 'answer-result.json').write_text(json.dumps(record(), indent=1, ensure_ascii=False) + '\n')
    recorded = json.loads((HERE / 'answer-result.json').read_text())
    graded = {name: [grade(recorded['questions'][name], a)[0] for a in answers]
              for name, answers in recorded['answers'].items()}
    print(json.dumps({'summary': summarize(recorded), 'graded': graded}, indent=2))
