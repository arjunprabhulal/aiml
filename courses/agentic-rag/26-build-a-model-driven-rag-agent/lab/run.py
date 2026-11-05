"""Default: exact-request replay. --live --execute-approved records capped Gemini calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import time
from agent import run, Limits, POLICY, SCHEMA
from evaluate import grade
from provider import Gemini, ReplayModel, Allowance, MODEL, CONFIG, ENDPOINT
from retrieval import RetrievalTools
from tools import load_snapshot

ROOT = Path(__file__).parent
RUN = ROOT / 'runs' / 'gemini'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def inputs():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
            sorted(list(ROOT.glob('*.py')) + list((ROOT / 'fixtures').glob('*.json')))}


def execute(live=False, only=None):
    cases = json.loads((ROOT / 'fixtures/cases.json').read_text())['cases']
    if only:
        cases = [c for c in cases if c['id'] == only]
    if not cases:
        raise ValueError('unknown_case')
    allowance, trials = Allowance(200), []
    started = time.monotonic()
    for repeat in (1, 2):
        for case in cases:
            for mode in ('fixed', 'agent'):
                name = f"{case['id']}-{mode}-{repeat}"
                path = RUN / (name + '.json')
                if live:
                    model = Gemini(allowance, save=lambda rows, p=path: write(p, rows))
                else:
                    model = ReplayModel(json.loads(path.read_text()))
                tools = RetrievalTools(load_snapshot())
                before = time.monotonic()
                try:
                    result = run(tools, model, case['question'], case['version'], mode=mode,
                                 clock=time.monotonic if live else lambda: 0)
                finally:
                    tools.close()
                if not live and model.index != len(model.records):
                    raise ValueError('unused_recorded_replies')
                trial = dict(id=name, case_id=case['id'], split=case['split'], repeat=repeat,
                             mode=mode, result=result, checks=grade(case, result))
                if live:
                    trial['elapsed_seconds'] = round(time.monotonic() - before, 3)
                    trial['provider_usage'] = [r.get('response', {}).get('usageMetadata', {}) for r in model.records]
                trials.append(trial)
                if live:
                    write(RUN / 'partial.json', trials)
                print(f"{name}: {result['status']} / {trial['checks']['outcome']} / "
                      f"queries={trial['checks']['trajectory']['queries']} / calls={result['usage']['model_calls']}", flush=True)
                if live and result['reason'].startswith('model_transport_failed'):
                    raise RuntimeError('Provider transport failed; saved partial run; no automatic retry')
    summary = {mode: {outcome: sum(t['checks']['outcome'] == outcome for t in trials if t['mode'] == mode)
                      for outcome in ('pass', 'fail', 'incomplete')} for mode in ('fixed', 'agent')}
    report = dict(execution_mode='live-Gemini-API' if live else 'offline-exact-request-replay',
                  model=MODEL, config=CONFIG, endpoint=ENDPOINT, batch_request_cap=allowance.limit,
                  limits=Limits().__dict__, cases_sha256=inputs()['cases.json'], summary=summary, trials=trials)
    if live:
        report.update(recorded_at=datetime.now(timezone.utc).isoformat(), actual_api_requests=allowance.used,
                      elapsed_seconds=round(time.monotonic() - started, 3), source_sha256=inputs(),
                      environment={'python': platform.python_version(), 'platform': platform.platform(), 'sqlite': sqlite3.sqlite_version},
                      cost={'currency_cost': None, 'note': 'Token usage recorded; no billing-price estimate or invoice available.'})
        write(RUN / 'result.json', report)
    else:
        saved = json.loads((RUN / 'result.json').read_text())
        saved_trials = [t for t in saved['trials'] if not only or t['case_id'] == only]
        expected_summary = {mode: {outcome: sum(t['checks']['outcome'] == outcome for t in saved_trials if t['mode'] == mode)
                                   for outcome in ('pass', 'fail', 'incomplete')} for mode in ('fixed', 'agent')}
        if report['summary'] != expected_summary:
            raise ValueError('replay_summary_changed')
        for a, b in zip(report['trials'], saved_trials, strict=True):
            if any(a[k] != b[k] for k in ('id', 'result', 'checks')):
                raise ValueError('replay_trial_changed:' + a['id'])
    print(json.dumps(summary, sort_keys=True), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--execute-approved', action='store_true')
    parser.add_argument('--case')
    args = parser.parse_args()
    if args.live and not args.execute_approved:
        print(json.dumps({'model': MODEL, 'config': CONFIG, 'endpoint': ENDPOINT,
                          'max_requests': 200, 'retries': 0, 'input_bytes_per_call': 30000}, indent=2))
    else:
        execute(args.live, args.case)
