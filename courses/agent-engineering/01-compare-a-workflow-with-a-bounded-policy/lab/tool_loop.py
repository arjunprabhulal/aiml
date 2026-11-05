"""Run one bounded document lookup with an offline or installed-model policy."""
import argparse
import json
from core import load, outcome, run, scripted, task_from


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--case', default='rollback-direct')
    p.add_argument('--provider', choices=['scripted', 'ollama'], default='scripted')
    p.add_argument('--save', help='Optional local trace JSON path')
    args = p.parse_args()
    case = next((c for c in load('cases.json') if c['id'] == args.case), None)
    if not case:
        p.error('unknown case')
    policy = scripted
    if args.provider == 'ollama':
        from provider import OllamaPolicy
        policy = OllamaPolicy()
    result = run(task_from(case), policy)
    for event in result['trace']:
        d = event['decision']
        print(f"turn {event['turn']}: {d['action']}")
    print('answer:', result.get('answer', 'none'))
    print('source:', result.get('citation', 'none'))
    print('stop:', result['stop'], '| independent outcome:', outcome(case, result))
    print('policy:', args.provider)
    if args.save:
        from pathlib import Path
        Path(args.save).write_text(json.dumps({'case': case['id'], 'policy': args.provider,
                                              'result': result}, indent=2) + '\n')


if __name__ == '__main__':
    main()
