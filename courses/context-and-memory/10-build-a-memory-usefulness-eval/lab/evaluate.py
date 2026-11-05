"""Evaluate what memory sends: recall, usefulness, stale and forgotten facts, and storage growth.

Three ways to fill the memory block of a request, under one facts quota:

managed-all       every current fact from a managed store, newest first
managed-relevant  current facts that share words with the question
append-all        every fact from an append-only store, newest first

The stores are filled from labeled events, which act as perfect extraction:
the managed store applies corrections and forget requests; the append-only
store keeps every fact and ignores both.
Lines are counted with the pinned Gemma 4 E2B tokenizer. The run is
deterministic: one trial. Storage is measured in rows; file sizes depend on the
SQLite version and are reported separately.
"""
import json
from pathlib import Path
import platform
import sqlite3
import tempfile
from tokenizer import count_text
from memory import Clock, MemoryStore, Scope, words

HERE = Path(__file__).parent


def apply(store: MemoryStore, scope: Scope, event: dict, managed: bool):
    current = [r for r in store.current(scope) if r['attribute'] == event['attribute']]
    source = f'turn-{event["turn"]}'
    if managed and event['op'] == 'correct' and current:
        store.correct(scope, current[-1]['id'], event['text'], source)
    elif managed and event['op'] == 'forget' and current:
        for row in current:
            store.forget(scope, row['id'], f'user request at {source}')
    elif event['op'] != 'forget':
        store.remember(scope, 'user', event['text'], source, attribute=event['attribute'] if managed else None)


def lines(rows: list[dict], quota: int) -> list[str]:
    kept, used = [], 0
    for row in rows:
        line = f'- [#{row["id"]}] {row["text"]}'
        if used + count_text(line) <= quota:
            kept.append(line)
            used += count_text(line)
    return kept


def newest(store, scope, question):
    return sorted(store.current(scope), key=lambda r: -r['id'])


def relevant(store, scope, question):
    wanted = words(question)
    scored = [(len(wanted & words(r['text'])), r) for r in store.current(scope)]
    return [r for s, r in sorted(scored, key=lambda p: (-p[0], -p[1]['id'])) if s]


STRATEGIES = {'managed-all': ('managed', newest), 'managed-relevant': ('managed', relevant),
              'append-all': ('append', newest)}


def grade(sent: list[str], question: dict) -> dict:
    has = lambda facts: [line for line in sent if any(f in line for f in facts)]
    found = [f for f in question['required'] if any(f in line for line in sent)]
    return {'question': question['question'], 'sent': len(sent), 'useful': len(has(question['required'])),
            'stale': len(has(question['stale'])), 'forgotten': len(has(question['forgotten'])),
            'found': len(found), 'required': len(question['required']),
            'missing': [f for f in question['required'] if f not in found],
            'memory_tokens': sum(map(count_text, sent))}


def summarize(rows: list[dict]) -> dict:
    sent = sum(r['sent'] for r in rows)
    required = sum(r['required'] for r in rows)
    return {'questions': len(rows), 'facts_found': sum(r['found'] for r in rows), 'facts_required': required,
            'recall': round(sum(r['found'] for r in rows) / required, 3),
            'lines_sent': sent, 'useful_lines': sum(r['useful'] for r in rows),
            'usefulness': round(sum(r['useful'] for r in rows) / sent, 3) if sent else None,
            'stale_lines': sum(r['stale'] for r in rows), 'forgotten_lines': sum(r['forgotten'] for r in rows),
            'memory_tokens': sum(r['memory_tokens'] for r in rows)}


def counts(store: MemoryStore, scope: Scope) -> dict:
    db = store.db
    return {'stored_rows': db.execute('SELECT count(*) FROM memories WHERE user_id = ?', (scope.user,)).fetchone()[0],
            'current_facts': len(store.current(scope)),
            'superseded_rows': db.execute('SELECT count(*) FROM memories WHERE user_id = ? AND id IN '
                                          '(SELECT supersedes FROM memories WHERE supersedes IS NOT NULL)',
                                          (scope.user,)).fetchone()[0],
            'deletion_records': len(store.deletions(scope))}


def run(cases: dict) -> dict:
    quota = cases['facts_quota']
    rows = {name: [] for name in STRATEGIES}
    growth = {'managed': [], 'append': []}
    file_bytes = {}
    with tempfile.TemporaryDirectory() as folder:
        stores = {kind: MemoryStore(str(Path(folder) / f'{kind}.sqlite3'), Clock()) for kind in ('managed', 'append')}
        for conversation in cases['conversations']:
            scope = Scope(conversation['user'], 'assistant')
            for event in conversation['events']:
                for kind, store in stores.items():
                    apply(store, scope, event, managed=kind == 'managed')
            for question in conversation['questions']:
                for name, (kind, order) in STRATEGIES.items():
                    sent = lines(order(stores[kind], scope, question['question']), quota)
                    rows[name].append({'user': conversation['user'], **grade(sent, question)})
        replay = cases['long_replay']
        scope = Scope(replay['user'], 'assistant')
        for event in replay['events']:
            for kind, store in stores.items():
                apply(store, scope, event, managed=kind == 'managed')
            if event['turn'] % replay['sample_every'] == 0:
                for kind, store in stores.items():
                    growth[kind].append({'turn': event['turn'], **counts(store, scope)})
        for kind, store in stores.items():
            store.close()
            file_bytes[kind] = (Path(folder) / f'{kind}.sqlite3').stat().st_size
    return {
        'facts_quota': quota, 'trials': 1,
        'grader': 'a line is useful if it contains a required fact; stale and forgotten lines contain a listed fact',
        'summary': {name: summarize(r) for name, r in rows.items()},
        'questions': rows,
        'growth': growth,
        'counter': 'Gemma 4 E2B tokenizer (tokenizer-manifest.json)',
        'environment': {'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
                        'file_bytes_after_replay': file_bytes},
    }


if __name__ == '__main__':
    print(json.dumps(run(json.loads((HERE / 'cases.json').read_text())), indent=2))
