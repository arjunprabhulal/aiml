"""Exercise declared request limits with local calls and a real local queue wait."""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from acceptance import Policy, handle, invoke, harness
import task

ROOT = Path(__file__).resolve().parent


async def experiment():
    policy = Policy(**json.loads((ROOT / 'policy.json').read_text()))
    cases = harness.load_cases(ROOT / 'cases.json', harness.load_task('task'))
    task.validate_inputs(cases)
    by_id = {case['id']: case for case in cases['cases']}
    case = by_id['v3-production-lookup']
    source = (ROOT / 'pages.json').read_bytes()
    results = {}

    async def run(name, chosen=policy, raw=source, selected=case, application=invoke, saturated=False):
        gate = chosen.gate()
        if saturated:
            async with gate.lease():
                result = await handle(selected, raw, chosen, gate, application)
        else:
            result = await handle(selected, raw, chosen, gate, application)
        result['capacity_after'] = gate.snapshot()
        results[name] = result

    await run('normal')

    def wrong_command(case, pages):
        output = invoke(case, pages)
        output['command_template'] = 'docuctl rollback RELEASE --env staging'
        return output

    await run('wrong_command', application=wrong_command)
    await run('oversized_source', raw=source + b' ' * policy.max_source_bytes)
    await run('output_limit', chosen=replace(policy, max_output_bytes=1))
    await run('queue_full', chosen=replace(policy, max_waiting=0), saturated=True)
    await run('wait_timeout', saturated=True)
    await run('required_refusal', selected=by_id['reader-proposal'])
    return {'mode': 'Local function calls and local capacity admission; no model, tokenizer or paid API',
            'assumption': 'Byte, capacity and queue-wait limits are declared scenario policy, not measured latency or monetary caps.',
            'files': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                      ('architecture.py', 'pages.json', 'cases.json', 'task.py', 'acceptance.py', 'inspect_acceptance.py', 'policy.json', 'vendor/harness.py', 'vendor/gate.py')},
            'scenarios': results}


def record():
    return asyncio.run(experiment())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--save', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = record()
    if args.check and result != json.loads((ROOT / 'result.json').read_text()):
        raise SystemExit('acceptance results or source bindings differ')
    if args.save:
        args.save.write_text(json.dumps(result, indent=2) + '\n')
    print('Declared request policy; actual local calls, byte counts and capacity outcomes')
    for name, row in result['scenarios'].items():
        print(f"{name}: called={row['called']}; quality={row['quality']['verdict']}; "
              f"resource={row['resource_status']}; bytes={row['output_bytes']}; meets_contract={row['meets_contract']}")
    print('Queue wait is bounded; execution time, memory and provider charges are not bounded by this policy.')


if __name__ == '__main__':
    main()
