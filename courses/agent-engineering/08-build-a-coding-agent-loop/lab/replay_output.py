"""Replay saved model responses through the real tools; render the actual result."""
import copy
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

from harness.loop import agent_events
from harness.tools import RepoTools

HERE = Path(__file__).resolve().parent


def comparable(messages):
    result = copy.deepcopy(messages)
    for message in result:
        if message.get('role') == 'tool' and message.get('tool_name') == 'run_tests':
            value = json.loads(message['content'])
            message['content'] = {key: value.get(key) for key in ('exit_code', 'error')}
    return result


def replay():
    saved = json.loads((HERE / 'recorded-run.json').read_text())
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp) / 'repo'
        shutil.copytree(HERE / 'sample_repo', work)
        tools = RepoTools(work)
        tests = (work / 'tests/test_path_rules.py').read_bytes()
        assert hashlib.sha256(tests).hexdigest() == saved['tests_sha256']
        before = tools.run_tests()
        assert before['exit_code'] == saved['before']['exit_code'] == 1
        turns = iter(saved['turns'])
        consumed = []

        def chat(messages, schemas):
            turn = next(turns)
            assert comparable(messages) == comparable(turn['messages'])
            consumed.append(turn)
            yield from copy.deepcopy(turn['chunks'])

        events = list(agent_events(chat, tools, saved['task'], saved['max_turns']))
        after = tools.run_tests()
        assert len(consumed) == len(saved['turns'])
        assert events[-1]['reason'] == saved['events'][-1]['reason'] == 'assistant_finished'
        assert after['exit_code'] == saved['after']['exit_code'] == 0
        assert (work / 'path_rules.py').read_text() == saved['result_source']
        unchanged = (work / 'tests/test_path_rules.py').read_bytes() == tests
        assert unchanged
        return {'mode': 'offline replay of saved model responses; actual local tool and test execution; no model request',
                'saved_model': saved['model'], 'saved_record_sha256': hashlib.sha256((HERE / 'recorded-run.json').read_bytes()).hexdigest(),
                'command': 'python replay_output.py',
                'python': sys.version, 'before': before, 'after': after,
                'response_turns': len(consumed), 'events': events, 'sample_tests_unchanged': unchanged}


def summary(result):
    return ' · '.join(re.findall(r'\d+ (?:failed|passed|error)', result['output'].splitlines()[-1]))


def render(record):
    esc = lambda value: html.escape(str(value))
    calls = [event for event in record['events'] if event['type'] == 'tool_start']
    cards = []
    for call in calls:
        result = next(event['result'] for event in record['events'] if event['type'] == 'tool_result' and event['turn'] == call['turn'] and event['index'] == call['index'])
        if call['name'] == 'read_file':
            detail = 'Read ' + result['path']
        elif call['name'] == 'replace_text':
            detail = f"Changed {result['path']}\nExact replacements: {result['replaced']}"
        else:
            detail = f"Exit code: {result['exit_code']}\n{summary(result)}"
        cards.append(f"<section><h2>Turn {esc(call['turn'])}: {esc(call['name'])}</h2><pre>{esc(detail)}</pre></section>")
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Coding-agent offline replay</title><style>
*{{box-sizing:border-box}}body{{margin:0;padding:24px;background:#fff;color:#192136;font-family:system-ui,sans-serif}}main{{max-width:760px;margin:auto;border:1px solid #dfe4ed;border-radius:8px;padding:24px}}h1{{font-size:30px;line-height:1.2;margin:0 0 12px}}header p{{font-size:18px;line-height:1.5;margin:8px 0}}.summary{{color:#274bc4}}.cards{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:18px 0}}section{{border:1px solid #dfe4ed;border-radius:5px;padding:14px;min-width:0}}h2{{font-size:19px;line-height:1.3;margin:0 0 12px}}pre{{margin:0;font:18px/1.45 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere}}footer{{font-size:17px;line-height:1.5;color:#596375;margin-top:18px}}
@media(max-width:600px){{body{{padding:16px}}main{{padding:16px}}h1{{font-size:26px}}header p{{font-size:17px}}.cards{{grid-template-columns:1fr}}h2{{font-size:18px}}pre{{font-size:17px}}footer{{font-size:16px}}}}
</style><main><header><h1>Coding-agent replay</h1><p>Saved model responses; tools and tests execute locally again.</p><p>No new model request.</p><p>Recorded model: {esc(record['saved_model'])}</p><p class="summary">Before repair: {esc(summary(record['before']))}</p></header><div class="cards">{''.join(cards)}<section><h2>Loop stopped</h2><pre>{esc(record['events'][-1]['reason'])}\n{esc(record['response_turns'])} saved response turns\n{esc(len(calls))} tool calls</pre></section><section><h2>Independent final test</h2><pre>Exit code: {esc(record['after']['exit_code'])}\n{esc(summary(record['after']))}\nTest file unchanged: {esc(record['sample_tests_unchanged'])}</pre></section></div><footer>This re-executes one saved attempt. A finished assistant message alone does not mean the sample tests pass, and replay does not measure a fresh model response.</footer></main></html>'''


if __name__ == '__main__':
    result = replay()
    (HERE / 'replay-output.json').write_text(json.dumps(result, indent=2) + '\n')
    (HERE / 'runtime-output.html').write_text(render(result))
    print(result['mode'])
    print('Before:', summary(result['before']))
    print('After:', summary(result['after']))
    print('Stop:', result['events'][-1]['reason'])
    print('Saved response turns:', result['response_turns'])
    print('Rendered runtime-output.html from actual replay results.')
