"""Write memories, close the store, reopen it from disk, then recall.

The baseline keeps the same memories in a Python list. The restart is simulated
in one process: the list is emptied where a new process would start empty.
"""
import json
from pathlib import Path
import tempfile
from memory import MemoryStore, Scope, fixed_clock, words


def run(scenario: dict) -> dict:
    first, second = scenario['sessions']
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder) / 'memory.sqlite3')
        store = MemoryStore(path, clock=fixed_clock())
        baseline = []  # the in-process alternative: lost when the process exits
        for write in first['writes']:
            scope = Scope(*write['as'])
            store.remember(scope, write['level'], write['text'], write['source'])
            baseline.append(write)
        store.close()
        baseline = []  # process restart

        store = MemoryStore(path, clock=fixed_clock())  # a new process opens the same file
        results = []
        for query in second['queries']:
            scope = Scope(*query['as'])
            recalled = store.recall(scope, query['query'])
            results.append({
                'scope': '/'.join(query['as']),
                'query': query['query'],
                'query_words': sorted(words(query['query'])),
                'visible_memories': store.count(scope),
                'recalled': recalled,
                'baseline_recalled_after_restart': len(baseline),
            })
        store.close()
    return {'stored': len(first['writes']), 'queries': results}


if __name__ == '__main__':
    scenario = json.loads(Path(__file__).with_name('scenario.json').read_text())
    print(json.dumps(run(scenario), indent=2))
