"""One local user-return workflow: prepare, train, evaluate, export and predict.

The synthetic fixture describes existing users. A prediction estimates a return
in the following 24 hours from the event count known in the preceding 24 hours.
No orchestration, registry, HTTP serving or production measurement is claimed.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from vendor import availability, baseline

HERE = Path(__file__).resolve().parent
FEATURE = 'recent_event_count'
PROJECT = 'user-return-24h-v1'
# Reuse the published baseline's fitting and scaling arithmetic. Only this
# standalone adapter configures its feature and class names; Rice files/results
# are never loaded, altered or relabelled as user-return results.
baseline.FEATURES = [FEATURE]
baseline.LABELS = ['not_returned', 'returned']
baseline.POSITIVE = 'returned'


def strict_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON field: ' + key)
            result[key] = value
        return result
    def reject(value):
        raise ValueError('non-finite JSON value: ' + value)
    return json.loads(Path(path).read_text(), object_pairs_hook=unique, parse_constant=reject)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as file:
        file.write(json.dumps(value, indent=2, allow_nan=False) + '\n')


def partition(at):
    day = availability.instant(at).date().isoformat()
    for name, start, end in [('training', '2026-01-03', '2026-01-08'),
                             ('validation', '2026-01-10', '2026-01-11'),
                             ('test', '2026-01-13', '2026-01-14')]:
        if start <= day <= end:
            return name
    return 'excluded'


def prepare(source):
    fixture = strict_json(source)
    result = availability.assemble(fixture['observations'], fixture['events'],
                                   fixture['labels'], fixture['assemble_at'])
    rows = [dict(row, split=partition(row['predict_at'])) for row in result['rows']]
    return {'format': 'return-cohort-v1', 'project': PROJECT, 'feature': FEATURE,
            'source_sha256': sha(source), 'as_of': result['as_of'], 'rows': rows,
            'excluded': result['excluded']}


def cohort(path):
    data = strict_json(path)
    if (not isinstance(data, dict) or data.get('format') != 'return-cohort-v1'
            or data.get('project') != PROJECT or data.get('feature') != FEATURE
            or not isinstance(data.get('rows'), list) or not data['rows']):
        raise ValueError('unsupported or empty cohort')
    ids = set()
    for row in data['rows']:
        if not isinstance(row, dict):
            raise ValueError('each cohort row must be an object')
        availability.check_id(row.get('id'))
        if row['id'] in ids:
            raise ValueError('duplicate cohort observation')
        ids.add(row['id'])
        count(row.get('feature_count'))
        if type(row.get('label')) is not int or row['label'] not in (0, 1):
            raise ValueError('label must be integer 0 or 1')
        if row.get('split') != partition(row.get('predict_at')):
            raise ValueError('row differs from the declared time split')
        if row['split'] == 'excluded':
            raise ValueError('cohort contains a row from a gap or unsupported window')
    return data


def count(value):
    if type(value) is not int or not 0 <= value <= 1000:
        raise ValueError('event count must be an integer between 0 and 1000')
    return value


def train(path):
    data = cohort(path)
    rows = [dict(x=[row['feature_count']], label='returned' if row['label'] else 'not_returned')
            for row in data['rows'] if row['split'] == 'training']
    if {row['label'] for row in rows} != set(baseline.LABELS):
        raise ValueError('training needs both outcome classes')
    scaler = baseline.fit_scaler(rows)
    fitted = baseline.train_logistic(rows, scaler)
    return {'format': 'return-model-v1', 'project': PROJECT, 'features': [FEATURE],
            'cohort_sha256': sha(path), 'training_rows': len(rows),
            'preprocessing': scaler,
            'estimator': {'weights': fitted['weights'], 'bias': fitted['bias']},
            'training_positive_rate': sum(r['label'] == 'returned' for r in rows) / len(rows),
            'settings': {'epochs': baseline.EPOCHS, 'learning_rate': baseline.LEARNING_RATE,
                         'threshold': 0.5, 'scaler_fitted_on': 'training'}}


def load_model(path):
    model = strict_json(path)
    if (not isinstance(model, dict) or model.get('format') != 'return-model-v1'
            or model.get('project') != PROJECT or model.get('features') != [FEATURE]):
        raise ValueError('unsupported model or feature order')
    try:
        weights = model['estimator']['weights']
        means, stds = model['preprocessing']['mean'], model['preprocessing']['std']
        values = [*weights, *means, *stds, model['estimator']['bias']]
        valid = (len(weights) == len(means) == len(stds) == 1
                 and all(type(v) in (int, float) and math.isfinite(v) for v in values)
                 and stds[0] > 0)
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise ValueError('invalid model weights or preprocessing')
    return model


def predict(model, event_count):
    value = count(event_count)
    scaled = (value - model['preprocessing']['mean'][0]) / model['preprocessing']['std'][0]
    probability = baseline.sigmoid(model['estimator']['weights'][0] * scaled + model['estimator']['bias'])
    return {'event_count': value, 'return_probability': probability,
            'predicted_return': int(probability >= 0.5)}


def evaluate(cohort_path, model_path, split='validation'):
    if split not in ('validation', 'test'):
        raise ValueError('evaluate validation or final test data')
    data, model = cohort(cohort_path), load_model(model_path)
    if model['cohort_sha256'] != sha(cohort_path):
        raise ValueError('model and cohort identities differ')
    rows = [row for row in data['rows'] if row['split'] == split]
    if not rows:
        raise ValueError('evaluation split is empty')
    predictions = [predict(model, row['feature_count']) for row in rows]
    correct = sum(p['predicted_return'] == r['label'] for p, r in zip(predictions, rows))
    baseline_prediction = int(model['training_positive_rate'] >= 0.5)
    return {'split': split, 'rows': len(rows), 'correct': correct,
            'accuracy': correct / len(rows),
            'majority_correct': sum(r['label'] == baseline_prediction for r in rows),
            'model_sha256': sha(model_path), 'cohort_sha256': sha(cohort_path),
            'execution': 'fresh local CPU fit; authored synthetic labels'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare');p.add_argument('--source', type=Path, default=HERE/'scenario.json');p.add_argument('--out', type=Path, required=True)
    p = commands.add_parser('train');p.add_argument('--cohort', type=Path, required=True);p.add_argument('--out', type=Path, required=True)
    p = commands.add_parser('evaluate');p.add_argument('--cohort', type=Path, required=True);p.add_argument('--model', type=Path, required=True);p.add_argument('--split', choices=['validation','test'], default='validation');p.add_argument('--out', type=Path, required=True)
    p = commands.add_parser('predict');p.add_argument('--model', type=Path, required=True);p.add_argument('--event-count', type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            value = prepare(args.source);save(args.out,value)
            value = {'written': str(args.out), 'rows': len(value['rows']),
                     'splits': {s:sum(r['split']==s for r in value['rows']) for s in ['training','validation','test']}}
        elif args.command == 'train':
            value = train(args.cohort);save(args.out,value)
            value = {'written': str(args.out), 'training_rows': value['training_rows'], 'features':value['features']}
        elif args.command == 'evaluate':
            value = evaluate(args.cohort,args.model,args.split);save(args.out,value)
        else:
            value = predict(load_model(args.model),args.event_count)
        print(json.dumps(value,indent=2,allow_nan=False))
    except (ValueError,KeyError,FileExistsError,FileNotFoundError) as error:
        parser.exit(2,str(error)+'\n')


if __name__ == '__main__':
    main()
