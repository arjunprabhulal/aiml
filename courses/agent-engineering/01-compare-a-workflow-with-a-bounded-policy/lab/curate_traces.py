"""Deduplicate task families, redact two known fields, and split before tuning."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from core import load, run, scripted, task_from


def redact(text):
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email]', text)
    return re.sub(r'\bTOKEN=[A-Za-z0-9_-]+', 'TOKEN=[removed]', text)


def partition(cases, family_splits):
    family_owner = {}
    for split, families in family_splits.items():
        for family in families:
            if family in family_owner:
                raise ValueError('a task family appears in more than one split')
            family_owner[family] = split
    output = {name: [] for name in family_splits}
    seen = {}
    for case in cases:
        clean = {**case, 'question': redact(case['question'])}
        # Case IDs are not a deduplication key: changing an ID must not leak a copy.
        fingerprint = hashlib.sha256(json.dumps([
            ' '.join(clean['question'].casefold().split()), clean['version']]).encode()).hexdigest()
        if fingerprint in seen:
            old = seen[fingerprint]
            if (old['family'], old['expected_doc'], old['expected_command']) != (
                    clean['family'], clean['expected_doc'], clean['expected_command']):
                raise ValueError('duplicate question has conflicting family or labels')
            continue
        if clean['family'] not in family_owner:
            raise ValueError('task family has no assigned split')
        seen[fingerprint] = clean
        output[family_owner[clean['family']]].append(clean)
    if any(not rows for rows in output.values()):
        raise ValueError('every split must contain at least one case')
    return output


def curate(cases, family_splits):
    """Run only the deduplicated, question-redacted cases in each fixed split."""
    splits = partition(cases, family_splits)
    return {name: [{'case': case, 'result': run(task_from(case), scripted)}
                   for case in rows] for name, rows in splits.items()}


def save(records, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for split, rows in records.items():
        if split not in {'train', 'development', 'test'}:
            raise ValueError('unknown split name')
        (directory / (split + '.json')).write_text(json.dumps(rows, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--save-dir', help='Write one local trace file per split')
    args = parser.parse_args()
    cases = load('cases.json')
    records = curate(cases, load('splits.json'))
    if args.save_dir:
        save(records, args.save_dir)
    print('Input:', len(cases), 'synthetic questions;', sum(map(len, records.values())), 'fresh scripted traces')
    for name, rows in records.items():
        print(name + ':', len(rows), 'questions;', len({r['case']['family'] for r in rows}), 'families')
    print('Redaction:', redact('owner@example.invalid TOKEN=demo_secret'))
    print('Split by task family before selecting a policy; keep the test set out of selection.')


if __name__ == '__main__':
    main()
