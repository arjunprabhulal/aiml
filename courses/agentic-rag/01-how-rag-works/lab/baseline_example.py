"""Inspect the original failed UTF-8 baseline case without making a model request."""
import hashlib
import json
from pathlib import Path

RECORD = Path(__file__).parent / 'runs/baseline-recording.json'
RECORD_SHA256 = '193d4c3c91e66432d3717bf85dced0034b572e804cd50efc246042b574baeaa0'

def load_case(path=RECORD):
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=RECORD_SHA256:
        raise ValueError('saved baseline bytes changed')
    return json.loads(raw)['responses']['utf8-write'][0]['output']

if __name__=='__main__':
    print('Mode: offline inspection of the saved baseline')
    print(json.dumps(load_case(),indent=2,ensure_ascii=False))
