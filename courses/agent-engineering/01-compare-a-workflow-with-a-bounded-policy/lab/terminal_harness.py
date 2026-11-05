"""A deliberately small repair task, with a restricted expression boundary."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from core import load

CHECKS = [tuple(pair) for pair in load('repair-task.json')['checks']]


def validate_patch(expression):
    if not isinstance(expression, str) or len(expression) > 64:
        raise ValueError('patch must be at most 64 characters')
    tree = ast.parse(expression, mode='eval')
    node = tree.body
    if (not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1
            or not isinstance(node.left, ast.Name) or node.left.id != 'attempt'
            or not isinstance(node.comparators[0], ast.Name) or node.comparators[0].id != 'max_attempts'
            or not isinstance(node.ops[0], (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq))):
        raise ValueError('only a comparison between attempt and max_attempts is allowed')
    return ast.unparse(node)


def check_candidate(expression, directory=None, *, timeout=2):
    if type(timeout) not in (int, float) or not 0 < timeout <= 2:
        raise ValueError('timeout must be positive and at most 2 seconds')
    try:
        expression = validate_patch(expression)
    except (ValueError, SyntaxError):
        return {'outcome': 'rejected_patch', 'passed': 0, 'total': len(CHECKS)}
    with tempfile.TemporaryDirectory(prefix='docuctl-repair-', dir=directory) as work:
        path = Path(work)
        (path / 'candidate.py').write_text(
            'def can_retry(attempt,max_attempts):\n'
            '    if type(attempt) is not int or type(max_attempts) is not int or attempt<0 or max_attempts<1:\n'
            '        raise ValueError("invalid retry inputs")\n'
            f'    return {expression}\n')
        # The checker uses a specification independent of the submitted expression.
        (path / 'check.py').write_text(
            'import json,sys\n'
            'sys.path.insert(0,sys.argv[1])\n'
            'from candidate import can_retry\n'
            f'checks={CHECKS!r}\n'
            'outcomes=[can_retry(a,m)==(a in range(m)) for a,m in checks]\n'
            'print(json.dumps({"passed":sum(outcomes),"total":len(outcomes)}))\n'
            'sys.exit(0 if all(outcomes) else 1)\n')
        try:
            process = subprocess.run([sys.executable, '-I', str(path / 'check.py'), str(path)],
                                     cwd=path, env={'PATH': os.defpath}, text=True,
                                     capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return {'outcome': 'timeout', 'passed': 0, 'total': len(CHECKS)}
        if len(process.stdout) > 8192 or process.returncode not in (0, 1):
            return {'outcome': 'checker_error', 'passed': 0, 'total': len(CHECKS)}
        result = json.loads(process.stdout)
        return {'outcome': 'passed' if process.returncode == 0 else 'failed',
                **result, 'exit_status': process.returncode}


def main():
    for expression in ('attempt <= max_attempts', 'attempt < max_attempts',
                       '__import__("os").getcwd()'):
        r = check_candidate(expression)
        print(f"{expression}: {r['outcome']} ({r['passed']}/{r['total']})")
    print('Fresh temporary workspace per candidate. This restricted task is not a general OS sandbox.')


if __name__ == '__main__':
    main()
