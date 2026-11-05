"""Consolidate one user's facts: merge duplicates and resolve conflicts.

A conflict is two current facts at the same level that name the same
attribute and say different things. The rules, in order:

1. duplicate: the same normalized text. Keep the copy with the stronger
   authority, the user's statement over an inference; between copies of the
   same authority keep the older, which has the first source. A restatement
   still counts as new: the kept copy ranks by its newest copy of the same
   authority in rule 3.
2. user statement over inference: keep the fact the user stated over one a
   model inferred, whatever their order.
3. newer statement: between facts of the same authority, keep the newer.

Retired memories stay stored with a resolution record. Facts without an
attribute are compared only for duplicates; a contradiction written in two
different ways is not detected.
"""
import re
from memory import MemoryStore, Scope

RULES = ('duplicate', 'user statement over inference', 'newer statement')


def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text.strip().lower()).rstrip('.')


def plan(store: MemoryStore, scope: Scope) -> list[tuple[int, int, str]]:
    """Decide what to retire, without changing the store."""
    facts = [row for row in store.current(scope, shadow=False) if row['kind'] == 'semantic']
    decisions = []
    groups: dict[tuple, list[dict]] = {}
    for row in facts:
        # Facts without an attribute are grouped by their text, so only exact duplicates meet.
        key = (row['task_id'], row['attribute'] or 'text:' + normalize(row['text']))
        groups.setdefault(key, []).append(row)
    for rows in groups.values():
        survivors, latest = [], {}
        # The user's statements first, then oldest first: the first copy of a text is the one kept.
        for row in sorted(rows, key=lambda r: (r['authority'] != 'user', r['id'])):
            twin = next((s for s in survivors if normalize(s['text']) == normalize(row['text'])), None)
            if twin:
                decisions.append((twin['id'], row['id'], RULES[0]))
                if row['authority'] == twin['authority']:
                    latest[twin['id']] = max(latest[twin['id']], row['id'])
            else:
                survivors.append(row)
                latest[row['id']] = row['id']
        if len(survivors) < 2:
            continue
        stated = [r for r in survivors if r['authority'] == 'user']
        pool = stated or survivors
        winner = max(pool, key=lambda r: latest[r['id']])
        for row in survivors:
            if row is not winner:
                rule = RULES[1] if stated and row['authority'] == 'inferred' else RULES[2]
                decisions.append((winner['id'], row['id'], rule))
    return sorted(decisions, key=lambda d: d[1])


def consolidate(store: MemoryStore, scope: Scope) -> dict:
    decisions = plan(store, scope)
    store.resolve(scope, decisions)
    unchecked = [row['id'] for row in store.current(scope, shadow=False)
                 if row['kind'] == 'semantic' and row['attribute'] is None]
    return {'resolved': [{'kept': k, 'retired': r, 'rule': rule} for k, r, rule in decisions],
            'facts_without_attribute': unchecked}
