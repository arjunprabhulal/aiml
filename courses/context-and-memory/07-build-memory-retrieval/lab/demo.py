"""Store one user's memories, then retrieve them per kind and with one pooled ranking."""
import json
from pathlib import Path
import tempfile
from memory import Clock, MemoryStore, Scope
from retrieval import QUOTAS, pooled, retrieve


def check(text: str, case: dict) -> dict:
    return {'missing': [f for f in case['required'] if f not in text],
            'stale': [f for f in case['stale'] if f in text]}


def run(scenario: dict) -> dict:
    scope = Scope(*scenario['scope'])
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
        results = []
        for case in scenario['queries']:
            packet = retrieve(store, scope, case['query'])
            baseline_ids = pooled(store, scope, case['query'], scenario['pooled_limit'])
            texts = {row['id']: row['text'] for row in store.current(scope)}
            baseline_text = '\n'.join(texts[i] for i in baseline_ids)
            results.append({'query': case['query'], 'sections': packet['record'],
                            'check': check(packet['content'], case),
                            'pooled': {'ids': baseline_ids, 'check': check(baseline_text, case)}})
        content = retrieve(store, scope, scenario['queries'][0]['query'])['content']
        store.close()
    return {'quotas': QUOTAS, 'results': results, 'first_query_block': content}


if __name__ == '__main__':
    scenario = json.loads(Path(__file__).with_name('scenario.json').read_text())
    print(json.dumps(run(scenario), indent=2))
