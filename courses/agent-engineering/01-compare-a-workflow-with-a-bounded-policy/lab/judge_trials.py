"""Compare a cheap grader with reference labels; distinguish any from all trials."""
from math import comb
from core import load, outcome


def format_grader(result):
    return bool(result.get('citation')) and 'docuctl ' in result.get('answer', '')


def confusion(rows, grade):
    counts = {key: 0 for key in ('TP', 'FP', 'FN', 'TN')}
    for row in rows:
        predicted, expected = bool(grade(row)), row['reference_label']
        counts[('T' if predicted == expected else 'F') + ('P' if predicted else 'N')] += 1
    return counts


def trial_metrics(passed, k):
    if not passed or any(type(x) is not bool for x in passed):
        raise ValueError('trials must be a nonempty list of Boolean outcomes')
    n, c = len(passed), sum(passed)
    if type(k) is not int or not 1 <= k <= n:
        raise ValueError('k must lie between 1 and the number of trials')
    # HumanEval finite-sample estimator, not1-(1-observed_rate)**k.
    any_k = 1 - (comb(n - c, k) / comb(n, k) if n - c >= k else 0)
    return {'passed': c, 'trials': n, 'pass_at_k': any_k,
            'all_k_iid_plugin': (c / n) ** k,
            'observed_any': any(passed), 'observed_all': all(passed)}


def main():
    rows = load('judge-cases.json')
    print('Reference set:', len(rows), 'authored synthetic answers; no model judge calls')
    for name, grade in [('format', lambda row: format_grader(row['result'])),
                        ('task contract', lambda row: outcome(row['case'], row['result']))]:
        c = confusion(rows, grade)
        print(name + ':', ' '.join(f'{key}={value}' for key, value in c.items()))
    score = trial_metrics([True, True, False, True], 2)
    print('Calculation fixture: 3 of 4 pass; any=True; all=False')
    print(f"pass@2={score['pass_at_k']:.4f}; all 2 IID plug-in={score['all_k_iid_plugin']:.4f}")
    print('The all-2 estimate assumes independent, unchanged trials; four fixture values are not a reliability study.')


if __name__ == '__main__':
    main()
