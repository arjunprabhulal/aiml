"""Compact request.json, run the drop-oldest baseline, and report every probe."""
from collections import Counter
import json
from pathlib import Path
from compactor import compact, drop_oldest, parse_request, probe_report
from tokenizer import count_request, counter

here = Path(__file__).parent
request = parse_request(json.loads((here / 'request.json').read_text()))
probes = json.loads((here / 'probes.json').read_text())
report = {'counter': counter().profile()}
for name, policy in (('compacted', compact), ('drop_oldest', drop_oldest)):
    result = policy(request, count_request)
    probes_result = probe_report(result['messages'], probes)
    report[name] = {**result, 'probes': probes_result,
                    'probe_totals': dict(sorted(Counter(p['status'] for p in probes_result).items()))}
print(json.dumps(report, indent=2, ensure_ascii=False))
