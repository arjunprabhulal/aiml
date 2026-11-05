"""Store conflicting and duplicate facts, consolidate them, and show what each task sees."""
import json
from pathlib import Path
import tempfile
from consolidate import consolidate
from memory import Clock, MemoryStore, Scope


def facts(store: MemoryStore, scope: Scope) -> list[dict]:
    return [{'id': r['id'], 'attribute': r['attribute'], 'level': 'task' if r['task_id'] else 'user',
             'text': r['text']} for r in store.current(scope) if r['kind'] == 'semantic']


def run(scenario: dict) -> dict:
    with tempfile.TemporaryDirectory() as folder:
        clock = Clock()
        store = MemoryStore(str(Path(folder) / 'memory.sqlite3'), clock)
        day = 0
        for item in scenario['memories']:
            clock.advance(days=item['day'] - day)
            day = item['day']
            store.remember(Scope(scenario['user'], item['task']), item['level'], item['text'], item['source'],
                           attribute=item.get('attribute'), authority=item.get('authority', 'user'))
        views = [Scope(*view) for view in scenario['views']]
        before = {f'{v.user}/{v.task}': facts(store, v) for v in views}
        report = consolidate(store, views[0])
        again = consolidate(store, views[0])
        after = {f'{v.user}/{v.task}': facts(store, v) for v in views}
        resolutions = store.resolutions(views[0])
        stored = store.db.execute('SELECT count(*) FROM memories').fetchone()[0]
        store.close()
    return {'before': before, 'report': report, 'second_run': again, 'after': after,
            'resolutions': resolutions, 'memories_still_stored': stored}


if __name__ == '__main__':
    scenario = json.loads(Path(__file__).with_name('scenario.json').read_text())
    print(json.dumps(run(scenario), indent=2))
