"""A reproducible supervised-learning baseline for the rice dataset.

Run with Python 3.11+ and no packages:
    python3 baseline.py              # development run: validation metrics only
    python3 baseline.py --final      # final run: also scores the test split once

The data is the UCI "Rice (Cammeo and Osmancik)" dataset, CC BY 4.0
(https://doi.org/10.24432/C5MW4Z), converted from ARFF to rice.csv.
"""
import argparse
import hashlib
import json
import math
import random
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / 'rice.csv'
DATA_SHA256 = 'ac5b63d257bab6bf013453f29b99285baa664038d1023c02033135f6e320eaec'
FEATURES = ['area', 'perimeter', 'major_axis_length', 'minor_axis_length',
            'eccentricity', 'convex_area', 'extent']
LABELS = ['Cammeo', 'Osmancik']
POSITIVE = 'Cammeo'
SALT = 'rice-split-v1'
SPLITS = (('training', 0.70), ('validation', 0.85), ('test', 1.00))
SPLIT_RATIOS = {'training': (7, 10), 'validation': (17, 20), 'test': (1, 1)}
LEARNING_RATE = 0.5
EPOCHS = 200


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_rows(path=DATA, expected_sha256=DATA_SHA256):
    """Read and validate the CSV. Refuse a file that differs from the recorded version."""
    if expected_sha256 is not None and file_sha256(path) != expected_sha256:
        raise ValueError(f'{Path(path).name} does not match the recorded SHA-256; '
                         'record a new data version before using it')
    lines = Path(path).read_text().splitlines()
    if not lines or lines[0].split(',') != FEATURES + ['class']:
        raise ValueError(f'unexpected header: {lines[0] if lines else "empty file"}')
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        cells = line.split(',')
        if len(cells) != len(FEATURES) + 1:
            raise ValueError(f'line {number}: expected {len(FEATURES) + 1} values, found {len(cells)}')
        try:
            values = [float(cell) for cell in cells[:-1]]
        except ValueError:
            raise ValueError(f'line {number}: a feature value is missing or not a number') from None
        if not all(math.isfinite(v) for v in values):
            raise ValueError(f'line {number}: a feature value is not finite')
        if cells[-1] not in LABELS:
            raise ValueError(f'line {number}: unknown class {cells[-1]!r}')
        # The row key is the raw feature text, so it does not depend on file order.
        rows.append({'key': ','.join(cells[:-1]), 'x': values, 'label': cells[-1]})
    return rows


def assign_split(key, salt=SALT):
    """Map a row key to a split with SHA-256: stable across runs, machines and row order."""
    digest = hashlib.sha256(f'{salt}:{key}'.encode()).digest()
    position = int.from_bytes(digest[:8], 'big')
    # Keep the 64-bit position as an integer: dividing the largest digest by
    # 2**64 as a float rounds it to 1.0 and can leave a valid key unassigned.
    for name, _ in SPLITS:
        numerator, denominator = SPLIT_RATIOS[name]
        if position * denominator < numerator * 2 ** 64:
            return name
    raise AssertionError('every 64-bit digest must belong to a split')


def split_rows(rows, salt=SALT):
    parts = {name: [] for name, _ in SPLITS}
    for row in rows:
        parts[assign_split(row['key'], salt)].append(row)
    for name, part in parts.items():
        missing = [label for label in LABELS if not any(r['label'] == label for r in part)]
        if missing:
            raise ValueError(f'{name} split has no rows of class {", ".join(missing)}')
    return parts


def content(row):
    """What a row is, independent of where it sits in the file or how its key is built."""
    return (tuple(row['x']), row['label'])


def membership(parts):
    return {content(row): name for name, part in parts.items() for row in part}


def shuffle_split(rows, seed=8):
    """The common alternative: shuffle with a seed, then cut by position. Used only for comparison."""
    order = list(range(len(rows)))
    random.Random(seed).shuffle(order)
    cut_a, cut_b = round(0.70 * len(rows)), round(0.85 * len(rows))
    parts = {name: [] for name, _ in SPLITS}
    for position, index in enumerate(order):
        parts['training' if position < cut_a else 'validation' if position < cut_b else 'test'].append(rows[index])
    return parts


def reload(lines, folder, name):
    """Write a variant of the data file and read it back through the normal loader."""
    path = Path(folder) / name
    path.write_text(''.join(line + '\n' for line in lines))
    return load_rows(path, expected_sha256=None)


def moved(before, after):
    """Rows present in both runs whose split differs, compared by row content."""
    return sum(before[c] != after[c] for c in before if c in after)


def order_experiment(path=DATA, new_rows=100, sorted_by='area', other_salt='rice-split-v2'):
    """Reload reordered, sorted and appended copies of the file and count rows that change split."""
    header, *body = Path(path).read_text().splitlines()
    column = FEATURES.index(sorted_by)
    # 'older' is the file before the last new_rows rows arrived; 'newest_first' lists those rows at the top.
    variants = {'original': body, 'reversed': body[::-1], 'older': body[:-new_rows],
                'newest_first': body[-new_rows:] + body[:-new_rows],
                'sorted': sorted(body, key=lambda line: float(line.split(',')[column]))}
    with tempfile.TemporaryDirectory() as folder:
        loaded = {name: reload([header] + lines, folder, f'{name}.csv') for name, lines in variants.items()}
    hashed = {name: membership(split_rows(rows)) for name, rows in loaded.items()}
    shuffled = {name: membership(shuffle_split(rows)) for name, rows in loaded.items()}
    resalted = membership(split_rows(loaded['original'], other_salt))
    return {
        'reversed_order': {'seeded_shuffle': moved(shuffled['original'], shuffled['reversed']),
                           'hash_split': moved(hashed['original'], hashed['reversed'])},
        'sorted_by_' + sorted_by: {'seeded_shuffle': moved(shuffled['original'], shuffled['sorted']),
                                   'hash_split': moved(hashed['original'], hashed['sorted'])},
        'added_rows': {'new_rows': new_rows,
                       'appended_seeded_shuffle': moved(shuffled['older'], shuffled['original']),
                       'appended_hash_split': moved(hashed['older'], hashed['original']),
                       'listed_first_seeded_shuffle': moved(shuffled['older'], shuffled['newest_first']),
                       'listed_first_hash_split': moved(hashed['older'], hashed['newest_first'])},
        'salt_changed': {'salt': other_salt, 'rows': len(loaded['original']),
                         'kept_split': len(loaded['original']) - moved(hashed['original'], resalted),
                         'expected_share_kept': round(0.70 ** 2 + 0.15 ** 2 + 0.15 ** 2, 4)},
    }


def fit_scaler(rows):
    """Mean and standard deviation per feature, computed from the rows given (training only)."""
    n = len(rows)
    means = [math.fsum(r['x'][j] for r in rows) / n for j in range(len(FEATURES))]
    stds = [math.sqrt(math.fsum((r['x'][j] - means[j]) ** 2 for r in rows) / n) or 1.0
            for j in range(len(FEATURES))]
    return {'mean': means, 'std': stds}


def scale(row, scaler):
    return [(v - m) / s for v, m, s in zip(row['x'], scaler['mean'], scaler['std'])]


def sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def train_logistic(rows, scaler, learning_rate=LEARNING_RATE, epochs=EPOCHS):
    """Full-batch gradient descent on the mean cross-entropy loss. Starts from zero weights."""
    xs = [scale(r, scaler) for r in rows]
    ys = [1.0 if r['label'] == POSITIVE else 0.0 for r in rows]
    weights, bias, n, losses = [0.0] * len(FEATURES), 0.0, len(rows), []
    for _ in range(epochs):
        ps = [sigmoid(math.fsum(w * v for w, v in zip(weights, x)) + bias) for x in xs]
        errors = [p - y for p, y in zip(ps, ys)]
        grads = [math.fsum(e * x[j] for e, x in zip(errors, xs)) / n for j in range(len(weights))]
        weights = [w - learning_rate * g for w, g in zip(weights, grads)]
        bias -= learning_rate * math.fsum(errors) / n
        losses.append(-math.fsum(math.log(max(p, 1e-12)) if y else math.log(max(1 - p, 1e-12))
                                 for p, y in zip(ps, ys)) / n)
    return {'weights': weights, 'bias': bias, 'losses': losses}


def predict_logistic(model, scaler, row):
    z = math.fsum(w * v for w, v in zip(model['weights'], scale(row, scaler))) + model['bias']
    return POSITIVE if z >= 0 else next(label for label in LABELS if label != POSITIVE)


def majority_label(rows):
    counts = {label: sum(r['label'] == label for r in rows) for label in LABELS}
    return max(LABELS, key=lambda label: (counts[label], label))


def evaluate(predictions, rows):
    matrix = {actual: {predicted: 0 for predicted in LABELS} for actual in LABELS}
    for predicted, row in zip(predictions, rows):
        matrix[row['label']][predicted] += 1
    correct = sum(matrix[label][label] for label in LABELS)
    return {'rows': len(rows), 'correct': correct, 'accuracy': round(correct / len(rows), 4),
            'recall': {label: round(matrix[label][label] / sum(matrix[label].values()), 4) for label in LABELS},
            'confusion': matrix}


def run(final=False, path=DATA, salt=SALT):
    rows = load_rows(path)
    parts = split_rows(rows, salt)
    training = parts['training']
    scaler = fit_scaler(training)
    model = train_logistic(training, scaler)
    majority = majority_label(training)
    record = {
        'data': {'file': Path(path).name, 'sha256': file_sha256(path), 'rows': len(rows),
                 'source': 'UCI Rice (Cammeo and Osmancik), CC BY 4.0, doi:10.24432/C5MW4Z'},
        'split': {'salt': salt, 'method': 'sha256(salt:raw feature text)',
                  'counts': {name: {label: sum(r['label'] == label for r in part) for label in LABELS}
                             for name, part in parts.items()}},
        'settings': {'learning_rate': LEARNING_RATE, 'epochs': EPOCHS, 'positive_class': POSITIVE,
                     'scaler_fitted_on': 'training'},
        'scaler': {'mean': [round(v, 4) for v in scaler['mean']], 'std': [round(v, 4) for v in scaler['std']]},
        'model': {'weights': [round(w, 4) for w in model['weights']], 'bias': round(model['bias'], 4),
                  'loss_first_epoch': round(model['losses'][0], 4), 'loss_last_epoch': round(model['losses'][-1], 4)},
        'majority_class': majority,
        'reproducibility': order_experiment(path),
        'validation': {
            'majority': evaluate([majority] * len(parts['validation']), parts['validation']),
            'logistic': evaluate([predict_logistic(model, scaler, r) for r in parts['validation']], parts['validation']),
        },
    }
    if final:
        record['test'] = {
            'majority': evaluate([majority] * len(parts['test']), parts['test']),
            'logistic': evaluate([predict_logistic(model, scaler, r) for r in parts['test']], parts['test']),
        }
        accuracy, n = record['test']['logistic']['accuracy'], len(parts['test'])
        # Normal approximation to the binomial: a rough guide to single-split noise, not an exact interval.
        record['test']['logistic']['standard_error'] = round(math.sqrt(accuracy * (1 - accuracy) / n), 4)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--final', action='store_true', help='also score the test split (do this once)')
    parser.add_argument('--out', help='write the run record to this JSON file')
    args = parser.parse_args()
    record = run(final=args.final)
    text = json.dumps(record, indent=1)
    if args.out:
        Path(args.out).write_text(text + '\n')
    v = record['validation']
    print(f"rows {record['data']['rows']}  split {json.dumps(record['split']['counts'])}")
    print(f"validation accuracy  majority {v['majority']['accuracy']:.4f}  logistic {v['logistic']['accuracy']:.4f}")
    if args.final:
        t = record['test']
        print(f"test accuracy        majority {t['majority']['accuracy']:.4f}  logistic {t['logistic']['accuracy']:.4f}")


if __name__ == '__main__':
    main()
