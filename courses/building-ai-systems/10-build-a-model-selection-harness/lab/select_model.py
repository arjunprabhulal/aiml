"""Choose a local model for one task: check each candidate, run labeled cases, then decide.

python3 select_model.py record   # talks to Ollama, writes selection-run.json
python3 select_model.py          # offline: reads selection-run.json, writes decision.json
Python 3.11+, standard library only.
"""
import argparse
import json
import math
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent


class SelectionError(RuntimeError):
    """The server could not answer, so the case cannot be graded."""


def load(name):
    return json.loads((HERE / name).read_text())


def local_fetch(base_url, timeout=120):
    """Return fetch(path, payload) for a loopback Ollama server. No retries."""
    url = urlsplit(base_url)
    if url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('This lesson accepts only a local HTTP model server.')
    if url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        raise ValueError('Use a server origin without credentials or a path.')
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Timeout must be positive and finite.')

    def fetch(path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(base_url.rstrip('/') + path, data=data,
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            raise SelectionError(f'HTTP {error.code} from {path}') from error
        except (TimeoutError, URLError) as error:
            raise SelectionError(f'No answer from {path}: {error}') from error
        except ValueError as error:
            raise SelectionError(f'Invalid JSON from {path}') from error
        if not isinstance(result, dict) or result.get('error'):
            raise SelectionError(f'Error object from {path}')
        return result
    return fetch


def inspect(candidate, requirements, fetch):
    """Check the installed artifact against the hard requirements. Sends no chat request."""
    installed = {m.get('name'): m for m in fetch('/api/tags').get('models', [])}
    tag = candidate['tag']
    if tag not in installed:
        return {'tag': tag, 'problems': ['not installed; pull it explicitly first']}
    item = installed[tag]
    problems = []
    if item.get('digest') != candidate['digest']:
        problems.append('installed digest differs from the pinned digest')
    show = fetch('/api/show', {'model': tag})
    info = show.get('model_info', {})
    context = next((v for k, v in info.items() if k.endswith('.context_length')), None)
    profile = {
        'tag': tag,
        'digest': item.get('digest'),
        'download_bytes': item.get('size'),
        'format': item.get('details', {}).get('format'),
        'parameter_size': item.get('details', {}).get('parameter_size'),
        'quantization': item.get('details', {}).get('quantization_level'),
        'capabilities': show.get('capabilities', []),
        'context_length': context,
        'artifact_license': info.get('general.license'),
    }
    if requirements['capability'] not in profile['capabilities']:
        problems.append(f"no {requirements['capability']} capability")
    if not isinstance(context, int) or context < requirements['context_tokens']:
        problems.append('context window smaller than required')
    if candidate['card_license'] not in requirements['licenses']:
        problems.append('model card license is not allowed')
    if str(profile['artifact_license']).casefold() != candidate['card_license'].casefold():
        problems.append('artifact license metadata differs from the model card')
    return {**profile, 'problems': problems}


def build_chat(tag, report, requirements):
    if not isinstance(report, str) or not report.strip():
        raise ValueError('A report must contain text.')
    if len(report) > requirements['max_report_characters']:
        raise ValueError('Report is longer than the application allows.')
    return {
        'model': tag,
        'messages': [{'role': 'system', 'content': requirements['system_prompt']},
                     {'role': 'user', 'content': report}],
        'stream': False,
        'think': False,
        'keep_alive': '5m',
        'options': {**requirements['options'], 'num_ctx': requirements['context_tokens'],
                    'num_predict': requirements['output_tokens']},
    }


def grade(response, expected, labels):
    """Request check, then output check, then task check. Returns pass, fail or incomplete."""
    message = response.get('message') or {}
    text = message.get('content') if isinstance(message.get('content'), str) else ''
    if response.get('done') is not True:
        return 'incomplete', 'response did not complete', text
    if response.get('done_reason') == 'length':
        return 'incomplete', 'output limit reached', text
    if message.get('tool_calls') or not text.strip():
        return 'incomplete', 'no text reply', text
    answer = text.strip()
    if answer not in labels:
        return 'fail', 'not an allowed label', answer
    if answer != expected:
        return 'fail', 'wrong label', answer
    return 'pass', 'expected label', answer


def run_cases(tag, cases, requirements, fetch, clock):
    rows = []
    for case in cases:
        body = build_chat(tag, case['report'], requirements)
        started = clock()
        try:
            response = fetch('/api/chat', body)
        except SelectionError as error:
            rows.append({'id': case['id'], 'expected': case['expected'], 'answer': None,
                         'status': 'incomplete', 'reason': str(error), 'client_ms': None})
            continue
        elapsed = round((clock() - started) * 1000, 1)
        status, reason, answer = grade(response, case['expected'], requirements['labels'])
        rows.append({'id': case['id'], 'expected': case['expected'], 'answer': answer,
                     'status': status, 'reason': reason, 'client_ms': elapsed,
                     'done_reason': response.get('done_reason'),
                     'server_load_ms': round(response.get('load_duration', 0) / 1_000_000, 1),
                     'input_tokens': response.get('prompt_eval_count'),
                     'output_tokens': response.get('eval_count')})
    return rows


def record(fetch, clock=time.perf_counter, hardware=None):
    requirements, candidates = load('requirements.json'), load('candidates.json')
    development = load('cases-development.json')['cases']
    held_out = load('cases-held-out.json')['cases']
    results = []
    for candidate in candidates['candidates']:
        profile = inspect(candidate, requirements, fetch)
        entry = {'profile': profile}
        if not profile['problems']:
            fetch('/api/generate', {'model': candidate['tag'], 'keep_alive': 0})
            started = clock()
            fetch('/api/chat', {'model': candidate['tag'], 'keep_alive': '5m',
                                'options': {'num_ctx': requirements['context_tokens']}})
            entry['load_request_ms'] = round((clock() - started) * 1000, 1)
            entry['development'] = run_cases(candidate['tag'], development, requirements, fetch, clock)
            entry['held_out'] = run_cases(candidate['tag'], held_out, requirements, fetch, clock)
        results.append(entry)
    memory = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    return {'recorded_on': time.strftime('%Y-%m-%d'),
            'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                            'hardware': hardware, 'memory_bytes': memory,
                            'ollama': fetch('/api/version').get('version')},
            'results': results}


def counts(rows):
    return {status: sum(r['status'] == status for r in rows) for status in ('pass', 'fail', 'incomplete')}


def decide(run, requirements):
    """Offline and deterministic. Uses development results only; held-out results are reported."""
    rows = []
    for entry in run['results']:
        profile = entry['profile']
        checks = [{'requirement': 'artifact checks', 'met': not profile['problems'],
                   'value': '; '.join(profile['problems']) or 'all passed'}]
        if not profile['problems']:
            development = counts(entry['development'])
            timings = [r['client_ms'] for r in entry['development'] if r['client_ms'] is not None]
            median = round(statistics.median(timings), 1) if timings else None
            checks.append({'requirement': 'development passes',
                           'met': development['pass'] >= requirements['development_passes_required'],
                           'value': f"{development['pass']} of {len(entry['development'])}"})
            checks.append({'requirement': 'median reply ms',
                           'met': median is not None and median <= requirements['median_reply_ms_limit'],
                           'value': median})
        rows.append({'tag': profile['tag'], 'download_bytes': profile.get('download_bytes'),
                     'eligible': all(c['met'] for c in checks), 'checks': checks,
                     'held_out': counts(entry['held_out']) if 'held_out' in entry else None})
    eligible = [r for r in rows if r['eligible']]
    chosen = min(eligible, key=lambda r: r['download_bytes'])['tag'] if eligible else None
    return {'chosen': chosen,
            'rule': 'Meet every requirement on development cases; break ties by the smaller download.',
            'candidates': rows}


def dumps(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', nargs='?', choices=['record', 'decide'], default='decide')
    parser.add_argument('--base-url', default='http://127.0.0.1:11434')
    parser.add_argument('--hardware', help='Describe the test machine in the run record.')
    args = parser.parse_args()
    try:
        if args.mode == 'record':
            run = record(local_fetch(args.base_url), hardware=args.hardware)
            (HERE / 'selection-run.json').write_text(dumps(run))
        decision = decide(load('selection-run.json'), load('requirements.json'))
    except (ValueError, SelectionError) as error:
        parser.exit(1, f'{error}\n')
    (HERE / 'decision.json').write_text(dumps(decision))
    print(dumps(decision), end='')
    return 0 if decision['chosen'] else 2


if __name__ == '__main__':
    sys.exit(main())
