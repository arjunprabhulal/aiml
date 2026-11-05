"""Grade actual candidate behavior instead of trusting a completion message."""
from terminal_harness import check_candidate
from core import load


def benchmark(candidates):
    if not candidates:
        raise ValueError('benchmark needs at least one candidate')
    ids = [c['id'] for c in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError('candidate IDs must be unique')
    return [{'id': c['id'], 'reported_done': c['reported_done'],
             'grade': check_candidate(c['expression'])} for c in candidates]


def main():
    candidates = load('benchmark-candidates.json')
    for row in benchmark(candidates):
        grade = row['grade']
        print(f"{row['id']}: says_done={row['reported_done']}; actual={grade['outcome']}; {grade['passed']}/{grade['total']}")
    print('Three controlled candidate patches; these are environment checks, not model success rates.')


if __name__ == '__main__':
    main()
