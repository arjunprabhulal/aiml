"""Run every strategy on every case and grade the selected context.

The graders check whether named facts reach the request. They do not call a
model and they do not grade an answer. The run is deterministic: one trial.
"""
import hashlib
import json
from pathlib import Path
import platform
from tokenizer import count_request, counter
from strategies import STRATEGIES, escape

HERE = Path(__file__).parent
CASE_FIELDS = {'id', 'split', 'kind', 'instructions', 'current', 'history', 'budget', 'required', 'stale'}


class CaseError(ValueError):
    pass


def load_cases(path: Path) -> list[dict]:
    cases = json.loads(path.read_text())
    seen = set()
    for case in cases:
        if set(case) != CASE_FIELDS:
            raise CaseError(f'{case.get("id")}: fields must be {sorted(CASE_FIELDS)}')
        if case['id'] in seen:
            raise CaseError(f'duplicate case id {case["id"]}')
        seen.add(case['id'])
        if case['split'] not in ('dev', 'held_out'):
            raise CaseError(f'{case["id"]}: split must be dev or held_out')
        if not case['required']:
            raise CaseError(f'{case["id"]}: a case needs at least one required fact')
        text = ' '.join(t['user'] + ' ' + t['assistant'] for t in case['history'])
        for fact in case['required'] + case['stale']:
            if fact not in text:
                raise CaseError(f'{case["id"]}: fact {fact!r} does not occur in the history')
    return cases


def grade(case: dict, selected: dict) -> dict:
    text = '\n'.join(m['content'] for m in selected['messages'])
    # Notes are escaped, so look for both spellings of each fact.
    present = lambda fact: fact in text or escape(fact) in text
    found = [fact for fact in case['required'] if present(fact)]
    stale = [fact for fact in case['stale'] if present(fact)]
    budget = case['budget']
    return {
        'case': case['id'],
        'split': case['split'],
        'kind': case['kind'],
        'turns': selected['turns'],
        'notes': selected['notes'],
        'input_tokens': selected['input_tokens'],
        'within_budget': selected['input_tokens'] + budget['max_new_tokens'] + budget['margin'] <= budget['context_limit'],
        'required_found': len(found),
        'required_total': len(case['required']),
        'missing': [fact for fact in case['required'] if fact not in found],
        'stale_included': stale,
    }


def summarize(rows: list[dict]) -> dict:
    found = sum(r['required_found'] for r in rows)
    total = sum(r['required_total'] for r in rows)
    return {
        'cases': len(rows),
        'facts_found': found,
        'facts_total': total,
        'fact_recall': round(found / total, 3),
        'complete_cases': sum(r['required_found'] == r['required_total'] for r in rows),
        'cases_with_stale_facts': sum(bool(r['stale_included']) for r in rows),
        'over_budget': sum(not r['within_budget'] for r in rows),
        'mean_input_tokens': round(sum(r['input_tokens'] for r in rows) / len(rows), 1),
    }


def run(path: Path = HERE / 'cases.json') -> dict:
    cases = load_cases(path)
    digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
    report = {
        'case_set': path.name,
        'case_set_sha256': digest(path),
        'strategies_sha256': digest(HERE / 'strategies.py'),
        'tokenizer_manifest_sha256': digest(HERE / 'tokenizer-manifest.json'),
        'environment': {'python': platform.python_version(), 'implementation': platform.python_implementation()},
        'counter': counter().profile(),
        'trials': 1,
        'grader': 'exact substring match of required and stale facts, raw or escaped, in the selected messages',
        'summary': {},
        'cases': {},
    }
    for name, strategy in STRATEGIES.items():
        rows = [grade(case, strategy(case, count_request)) for case in cases]
        report['cases'][name] = rows
        report['summary'][name] = {split: summarize([r for r in rows if r['split'] == split])
                                   for split in ('dev', 'held_out')}
    return report


if __name__ == '__main__':
    print(json.dumps(run(), indent=2, ensure_ascii=False))
