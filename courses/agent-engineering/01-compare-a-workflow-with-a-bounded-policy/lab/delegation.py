"""Account for independent worker contexts and fixed delegation overhead."""
from concurrent.futures import ThreadPoolExecutor
from core import Task, load, run, scripted


def worker(task, *, turns=4):
    return run(task, scripted, max_turns=turns)


def gather(jobs):
    ids = [task.id for task in jobs]
    if len(ids) != len(set(ids)):
        raise ValueError('worker task IDs must be unique')
    if not jobs or len(jobs) > 2:
        raise ValueError('this coordinator accepts one or two workers')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, jobs))
    if any(r['stop'] != 'final' for r in results):
        return {'stop': 'incomplete', 'workers': dict(zip(ids, results))}
    return {'stop': 'final', 'workers': dict(zip(ids, results)),
            'tool_calls': sum(r['tool_calls'] for r in results),
            'policy_turns': sum(r['turns'] for r in results),
            'dispatches': len(jobs), 'merge_checks': 1}


def main():
    jobs = [Task(**job) for job in load('delegation-jobs.json')]
    # A sequential controller performs the same two sub-tasks, with the same limits.
    sequential = [worker(job) for job in jobs]
    delegated = gather(jobs)
    print('Same 2 tasks, same read-only tools, fresh state for each task.')
    print('sequential:', sum(r['turns'] for r in sequential), 'policy turns;',
          sum(r['tool_calls'] for r in sequential), 'tool calls')
    print('delegated:', delegated['policy_turns'], 'policy turns;',
          delegated['tool_calls'], 'tool calls;', delegated['dispatches'], 'dispatches; 1 merge check')
    for id, result in delegated['workers'].items():
        print(id + ':', result['citation'])
    print('Scripted policies; no model latency, price or quality advantage was measured.')


if __name__ == '__main__':
    main()
