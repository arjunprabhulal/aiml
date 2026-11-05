"""The reviewed local function and five single-fault probes; no language model."""
import copy
import json
from pathlib import Path
from architecture import Request, answer

ROOT = Path(__file__).resolve().parent
PAGES = json.loads((ROOT / 'pages.json').read_text())


class ContractSystem:
    mode = 'local_function'
    model = prompt = tools = None
    version = '1'

    def __init__(self, fault='none'):
        if fault not in {'none', 'source', 'permission', 'approval', 'format', 'no_output'}:
            raise ValueError('unknown controlled fault')
        self.fault = fault
        self.name = 'filtered-lookup' if fault == 'none' else f'controlled-{fault}'

    def respond(self, case, trial):
        request = Request(**case['input']['request'])
        pages = copy.deepcopy(PAGES)
        if case['input'].get('source_mode') == 'conflicting':
            pages.append(dict(pages[-1], id='conflicting-production', command='conflicting command'))
        if self.fault == 'permission' and case['id'] == 'reader-proposal':
            request = Request(**{**case['input']['request'], 'role': 'maintainer'})
        if self.fault == 'source' and case['id'] == 'v3-production-lookup':
            request = Request(operation='lookup_rollback', version='2', environment='staging')
        if self.fault == 'no_output' and case['id'] == 'v3-staging-lookup':
            return None
        output = answer(request, pages)
        if self.fault == 'approval' and case['id'] == 'maintainer-proposal':
            output['approval_required'] = False
        if self.fault == 'format' and case['id'] == 'v2-staging-lookup':
            del output['citation']
        return output
