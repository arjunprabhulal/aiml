"""Run every labeled question in both modes and grade the answers. Python 3.11+, offline.

    python3 evaluate.py            # replay recorded answers and vectors
    python3 evaluate.py --record   # ask the local Ollama server for anything not recorded

Grades, per question and mode: pass, fail or incomplete. An answerable question
passes when the answer contains one expected string as a whole word and a
claim cites an expected source. An unanswerable question passes when the reply
says the sources lack the answer and makes no claims. incomplete means the
reply could not be checked. Writes evaluation.json.
"""
import argparse
import json
import re
import statistics
from pathlib import Path

from rag import MODES, TOP_K, answer, models
from sources import load_sources

ROOT = Path(__file__).resolve().parent


def contains(text, expected):
    """Whole-word, case-insensitive match: '0' matches neither '10' nor the 0 in '0.32.14'."""
    return re.search(r'(?<![\w.])' + re.escape(expected.casefold()) + r'(?!\w|\.\d)', text.casefold()) is not None


def grade(question, result):
    if result['status'] == 'incomplete':
        return None
    reply = result['reply']
    if not question['expected']:
        return reply['not_in_sources'] and not reply['claims']
    labels = {r['label']: r['id'] for r in result['retrieved']}
    cited = {labels.get(c['source'].strip().strip('[]')) for c in reply['claims']}
    return any(contains(reply['answer'], e) for e in question['expected']) and bool(cited & set(question['sources']))


def summarize(rows):
    grades = [row['grade'] for row in rows]
    return {'questions': len(rows), 'pass': sum(g is True for g in grades), 'fail': sum(g is False for g in grades),
            'incomplete': sum(g is None for g in grades),
            'verified': sum(r['status'] == 'verified' for r in rows),
            'flagged': sum(r['status'] == 'flagged' for r in rows),
            'pass_and_flagged': sum(r['grade'] is True and r['status'] == 'flagged' for r in rows),
            'fail_and_verified': sum(r['grade'] is False and r['status'] == 'verified' for r in rows),
            'source_retrieved': sum(r['source_retrieved'] for r in rows)}


def evaluate(questions, embedder, model, sources):
    rows = []
    for q in questions:
        for mode in MODES:
            result = answer(q['question'], mode, embedder, model, sources)
            retrieved = {r['id'] for r in result['retrieved']}
            rows.append({'id': q['id'], 'split': q['split'], 'mode': mode, 'grade': grade(q, result),
                         'source_retrieved': not q['sources'] or bool(retrieved & set(q['sources'])),
                         **{k: result[k] for k in ('status', 'flags', 'retrieved', 'reply', 'raw', 'model')}})
    groups = {}
    for row in rows:
        groups.setdefault(f'{row["split"]}/{row["mode"]}', []).append(row)
    times = [row['model']['total_ms'] for row in rows]
    manifest = json.loads((ROOT / 'model-manifest.json').read_text())
    return {'top_k': TOP_K, 'sources': len(sources),
            'run': {'answer_model': {k: manifest['vision'][k] for k in ('ollama_tag', 'ollama_digest')},
                    'embedding_model': {k: manifest['embedding'][k] for k in ('ollama_tag', 'ollama_digest')},
                    'ollama_version': manifest['vision']['ollama_version'],
                    'options': manifest['generation_options'], 'recorded_with': manifest['vision']['recorded_with']},
            'results': {key: summarize(group) for key, group in sorted(groups.items())},
            'answer_ms_median': statistics.median(times), 'answer_ms_max': max(times),
            'per_question': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    questions = json.loads((ROOT / 'questions.json').read_text())['questions']
    embedder, model = models('record' if args.record else 'replay')
    result = evaluate(questions, embedder, model, load_sources())
    (ROOT / 'evaluation.json').write_text(json.dumps(result, indent=1) + '\n')
    for key, summary in result['results'].items():
        print(key, summary)


if __name__ == '__main__':
    main()
