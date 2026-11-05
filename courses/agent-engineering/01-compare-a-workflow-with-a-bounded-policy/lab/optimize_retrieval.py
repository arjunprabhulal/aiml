"""Select a real retrieval configuration on development cases, then evaluate once."""
from dataclasses import dataclass
from core import Documents, load
from curate_traces import partition


@dataclass(frozen=True)
class Candidate:
    name: str
    expand: bool
    top_k: int


CANDIDATES = (Candidate('literal-k1', False, 1), Candidate('glossary-k1', True, 1),
              Candidate('glossary-k2', True, 2))


def evaluate(candidate, cases):
    if not cases:
        raise ValueError('cannot score an empty case set')
    docs, passed, returned = Documents(), 0, 0
    for case in cases:
        hits = docs.search(case['question'], case['version'],
                           expand=candidate.expand, top_k=candidate.top_k)
        passed += case['expected_doc'] in [hit['id'] for hit in hits]
        returned += len(hits)
    return {'hits': passed, 'total': len(cases), 'returned': returned}


def select(development, *, candidates=CANDIDATES):
    if not candidates:
        raise ValueError('at least one candidate is required')
    scores = [(candidate, evaluate(candidate, development)) for candidate in candidates]
    # Maximize hits, then prefer less context; the name makes remaining ties stable.
    chosen, _ = min(scores, key=lambda row: (-row[1]['hits'], row[1]['returned'], row[0].name))
    return chosen, scores


def main():
    splits = partition(load('cases.json'), load('splits.json'))
    chosen, scores = select(splits['development'])
    for candidate, score in scores:
        print(f"development {candidate.name}: {score['hits']}/{score['total']} source hits; {score['returned']} passages")
    # Test labels are first used after selection has returned a frozen candidate.
    score = evaluate(chosen, splits['test'])
    print('selected:', chosen.name)
    print(f"held-out {chosen.name}: {score['hits']}/{score['total']} source hits; {score['returned']} passages")
    print('Metric: correct source in returned passages, not answer quality or model reliability.')


if __name__ == '__main__':
    main()
