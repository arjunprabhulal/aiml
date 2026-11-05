"""Record what each wire format sends and receives, then compare the adapters offline.

python3 record_wire.py record   # needs Ollama with gemma4:e2b and qwen3.5:0.8b; writes wire-record.json
python3 record_wire.py          # offline: replays wire-record.json through the adapters, writes contract-report.json
Python 3.11+, standard library only.
"""
import argparse
import json
import platform
import time
from pathlib import Path

from urllib.request import urlopen

from adapters import ADAPTERS, AdapterError, ChatRequest, http_post, local_origin, validate

HERE = Path(__file__).resolve().parent
MODELS = ('gemma4:e2b', 'qwen3.5:0.8b')
MESSAGES = (('system', 'Answer in one short sentence.'), ('user', 'What does HTTP stand for?'))
CASES = {
    'complete': ('{model}', ChatRequest(MESSAGES, max_tokens=48)),
    'output-limit': ('{model}', ChatRequest(MESSAGES, max_tokens=3)),
    'missing-model': ('aiml-missing:never', ChatRequest(MESSAGES, max_tokens=48)),
    'thinking-left-on': ('{model}', ChatRequest(MESSAGES, max_tokens=48)),
}
THINKING_KEYS = {'ollama-native': 'think', 'openai-compatible': 'reasoning_effort'}


def wire_body(adapter, model, case, request):
    """The adapter's own body, except the thinking-left-on case, which drops the thinking switch."""
    body = adapter.body(model, request)
    if case == 'thinking-left-on':
        body.pop(THINKING_KEYS[adapter.name])
    return body


def record(base_url='http://127.0.0.1:11434', post=http_post, clock=time.perf_counter):
    rows = []
    for model in MODELS:
        for name, Adapter in ADAPTERS.items():
            adapter = Adapter(base_url)
            for case, (target, request) in CASES.items():
                validate(request)
                body = wire_body(adapter, target.format(model=model), case, request)
                started = clock()
                status, raw = post(adapter.base_url + adapter.path, body, {'Content-Type': 'application/json'}, 120)
                rows.append({'model': model, 'adapter': name, 'case': case, 'request': body,
                             'status': status, 'body': raw.decode('utf-8'),
                             'client_ms': round((clock() - started) * 1000, 1)})
    origin = local_origin(base_url)
    with urlopen(origin + '/api/version', timeout=10) as response:
        version = json.load(response)['version']
    with urlopen(origin + '/api/tags', timeout=10) as response:
        digests = {m['name']: m['digest'] for m in json.load(response)['models'] if m['name'] in MODELS}
    return {'recorded_on': time.strftime('%Y-%m-%d'),
            'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                            'ollama': version, 'digests': digests},
            'rows': rows}


def outcome(row):
    """Replay one recorded response through the adapter's own parser."""
    adapter = ADAPTERS[row['adapter']]()
    try:
        r = adapter.parse(row['status'], row['body'].encode('utf-8'))
    except AdapterError as error:
        return {'error': error.kind, 'message': str(error)}
    return {'text': r.text, 'finish': r.finish, 'input_tokens': r.input_tokens, 'output_tokens': r.output_tokens}


def report(record_data):
    """Offline and deterministic: one outcome per model, case and adapter, and whether the two agree."""
    table = {}
    for row in record_data['rows']:
        table.setdefault(row['model'], {}).setdefault(row['case'], {})[row['adapter']] = outcome(row)
    for cases in table.values():
        for outcomes in cases.values():
            native, compatible = outcomes['ollama-native'], outcomes['openai-compatible']
            outcomes['agree'] = native == compatible
    return table


def dumps(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', nargs='?', choices=['record', 'report'], default='report')
    parser.add_argument('--base-url', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    if args.mode == 'record':
        (HERE / 'wire-record.json').write_text(dumps(record(args.base_url)))
    data = report(json.loads((HERE / 'wire-record.json').read_text()))
    (HERE / 'contract-report.json').write_text(dumps(data))
    for model, cases in data.items():
        for case, outcomes in cases.items():
            print(f"{model:14} {case:17} agree={outcomes['agree']!s:5} "
                  f"{outcomes['ollama-native'].get('text', outcomes['ollama-native'].get('error'))!r:50.50} "
                  f"{outcomes['openai-compatible'].get('text', outcomes['openai-compatible'].get('error'))!r:.50}")


if __name__ == '__main__':
    main()
