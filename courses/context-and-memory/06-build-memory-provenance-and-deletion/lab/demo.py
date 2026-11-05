"""Replay scenario.json: correct a memory, let one expire, forget one.

The scenario runs twice: with secure_delete on (the store's default) and off.
After each run the demo checks whether the forgotten text is still in the file.
"""
import json
from pathlib import Path
import tempfile
from memory import Clock, MemoryStore, Scope


def replay(scenario: dict, secure_delete: bool) -> dict:
    scope = Scope(*scenario['user'])
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'memory.sqlite3'
        clock = Clock()
        store = MemoryStore(str(path), clock, secure_delete=secure_delete)
        ids, day, log = {}, 0, []
        for step in scenario['steps']:
            clock.advance(days=step['day'] - day)
            day = step['day']
            op = step['op']
            entry = {'day': day, 'op': op}
            if op == 'remember':
                ids[step['key']] = store.remember(scope, step['level'], step['text'], step['source'],
                                                  step.get('ttl_days'))
                entry['id'] = ids[step['key']]
            elif op == 'correct':
                ids[step['new_key']] = store.correct(scope, ids[step['key']], step['text'], step['source'])
                entry.update(corrected=ids[step['key']], id=ids[step['new_key']])
            elif op == 'recall':
                entry.update(query=step['query'], recalled=store.recall(scope, step['query']))
            elif op == 'history':
                entry['versions'] = store.history(scope, ids[step['key']])
            elif op == 'purge_expired':
                entry['removed'] = store.purge_expired()
            elif op == 'forget':
                entry['deleted_ids'] = store.forget(scope, ids[step['key']], step['reason'])
            elif op == 'deletions':
                entry['records'] = store.deletions(scope)
            log.append(entry)
        store.close()
        raw = path.read_bytes()
        return {'secure_delete': secure_delete, 'steps': log,
                'forgotten_text_in_file': scenario['probe_text'].encode() in raw}


if __name__ == '__main__':
    scenario = json.loads(Path(__file__).with_name('scenario.json').read_text())
    on, off = replay(scenario, True), replay(scenario, False)
    assert on['steps'] == off['steps']
    print(json.dumps({'steps': on['steps'],
                      'forgotten_text_in_file': {'secure_delete_on': on['forgotten_text_in_file'],
                                                 'secure_delete_off': off['forgotten_text_in_file']}}, indent=2))
