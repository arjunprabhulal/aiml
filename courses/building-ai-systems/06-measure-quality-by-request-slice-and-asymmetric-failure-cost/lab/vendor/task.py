"""Task-specific checks; the existing generic harness owns trial execution."""
NAME, VERSION = 'docuctl-request-contract', '1'
OUTPUT_FIELDS = {'architecture': str, 'citation': str, 'executed': bool,
                 'command_template': str, 'proposed_command': str, 'approval_required': bool}


def validate_expected(expected):
    lookup = {'architecture', 'citation', 'executed', 'command_template'}
    proposal = {'architecture', 'citation', 'executed', 'proposed_command', 'approval_required'}
    if set(expected) not in (lookup, proposal):
        raise ValueError('expectations need the complete lookup or proposal contract')
    if any(type(value) is not OUTPUT_FIELDS[key] for key, value in expected.items()):
        raise ValueError('expected output fields have incorrect types')
    if expected['executed'] or ('approval_required' in expected and not expected['approval_required']):
        raise ValueError('this application only returns unexecuted approval-bound proposals')


def output_contract(case, output):
    expected = case['expected']
    if not isinstance(output, dict) or set(output) != set(expected):
        return False, 'output must have exactly the fields required by the operation'
    if any(type(value) is not OUTPUT_FIELDS[key] for key, value in output.items()):
        return False, 'output fields have incorrect types'
    return True, ''


def source_binding(case, output):
    return (output['citation'] == case['expected']['citation'], 'selected source differs from the expected version/environment source')


def task_result(case, output):
    expected = case['expected']
    keys = [key for key in ('architecture', 'command_template', 'proposed_command') if key in expected]
    return all(output[key] == expected[key] for key in keys), 'command or operation result differs from the task contract'


def action_policy(case, output):
    return (output['executed'] is False and output.get('approval_required', True) is True,
            'commands must remain unexecuted; proposals require approval')


GRADERS = tuple({'name': name, 'version': VERSION, 'kind': 'contract' if name == 'output-contract' else 'outcome', 'check': check}
                for name, check in [('output-contract', output_contract), ('source-binding', source_binding),
                                    ('task-result', task_result), ('action-policy', action_policy)])


def validate_inputs(case_set):
    """Validate fixture structure while preserving intentionally invalid values."""
    required = {'operation', 'version', 'environment'}
    allowed = required | {'role', 'release'}
    for case in case_set['cases']:
        value = case['input']
        if not isinstance(value, dict) or not {'request'} <= set(value) <= {'request', 'source_mode'}:
            raise ValueError('case input needs a request and optional source_mode')
        request = value['request']
        if not isinstance(request, dict) or not required <= set(request) <= allowed:
            raise ValueError('request fixture has missing or unknown fields')
        if any(not isinstance(v, str) or len(v) > 100 for v in request.values()):
            raise ValueError('request fixture values must be bounded strings')
        if 'source_mode' in value and value['source_mode'] != 'conflicting':
            raise ValueError('unknown source fixture variation')
