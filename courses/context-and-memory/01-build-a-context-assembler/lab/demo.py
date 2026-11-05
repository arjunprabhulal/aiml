"""Assemble request.json with the policy and the naive baseline; print both."""
import json
from pathlib import Path
from assembler import assemble, audit, naive_truncate
from contracts import parse_request
from tokenizer import count_request, counter

data = json.loads(Path(__file__).with_name('request.json').read_text())
request = parse_request(data)
result = assemble(request, count_request)
evidence_first = assemble(parse_request({**data, 'fill_order': ['evidence', 'history']}), count_request)
baseline = naive_truncate(request, count_request)
report = {
    'counter': counter().profile(),
    'assembled': {**result, 'audit': audit(result['messages'], request.instructions)},
    'evidence_first': {key: evidence_first[key] for key in
                       ('messages', 'fill_order', 'input_tokens', 'kept_evidence', 'dropped_evidence',
                        'kept_turns', 'dropped_turns', 'trace')},
    'baseline': {**baseline, 'audit': audit(baseline['messages'], request.instructions),
                 'question_kept': any(request.current in (m.get('content') or '') for m in baseline['messages'])},
}
print(json.dumps(report, indent=2, ensure_ascii=False))
