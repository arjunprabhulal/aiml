"""Compare a fixed workflow and a scripted decision loop on the same cases."""
from core import Documents, load, outcome, run, scripted, task_from, words


def keyword_route(task):
    """Fixed keyword route, followed by one version-scoped read."""
    routes = {'deploy': 'deploy', 'rollback': 'rollback', 'tokens': 'tokens',
              'config': 'config', 'migrate': 'migrate', 'releases': 'releases',
              'logs': 'logs', 'health': 'health'}
    topics = [topic for term, topic in routes.items() if term in words(task.question)]
    if len(topics) != 1:
        return {'stop': 'needs_review', 'tool_calls': 0}
    id = f'{topics[0]}-{task.version}'
    try:
        page = Documents().read(id, task.version)
    except ValueError:
        return {'stop': 'needs_review', 'tool_calls': 1}
    return {'stop': 'final', 'answer': page['command'], 'citation': id, 'tool_calls': 1}


def workflow(task):
    """Fixed search/read sequence, using the same search settings as the loop."""
    docs = Documents()
    hits = docs.search(task.question, task.version, expand=True, top_k=2)
    if not hits:
        return {'stop': 'needs_review', 'tool_calls': 1}
    page = docs.read(hits[0]['id'], task.version)
    return {'stop': 'final', 'answer': page['command'], 'citation': page['id'], 'tool_calls': 2}


def compare(cases):
    report = {}
    for name, execute in [('keyword route', keyword_route), ('search/read workflow', workflow),
                          ('scripted loop', lambda t: run(t, scripted, max_turns=3, max_tools=2))]:
        results = [execute(task_from(case)) for case in cases]
        report[name] = {'passed': sum(outcome(c, r) for c, r in zip(cases, results)),
                        'total': len(cases), 'tool_calls': sum(r['tool_calls'] for r in results)}
    return report


if __name__ == '__main__':
    cases = load('cases.json')
    print('Task: return the exact staging command and a version-matched source.')
    for name, row in compare(cases).items():
        print(f"{name}: {row['passed']}/{row['total']} outcomes; {row['tool_calls']} tool calls")
    print('The loop uses scripted decisions here; these are not model-quality scores.')
