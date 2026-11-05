"""Exercise checkpoint input-identity checks without another training job."""
import copy
import json
from pathlib import Path
import sys
import tempfile

import checkpoint as ck
import train as t
from bpe import Tokenizer

ROOT = Path(__file__).parent


def inspect():
    tok = Tokenizer.load(ROOT / 'tokenizer.json')
    text = (ROOT / 'corpus.txt').read_text()
    identity = ck.input_signature(tok, text)
    changed_corpus = ck.input_signature(tok, text.replace('red', 'blue'))
    changed_tok = Tokenizer(list(reversed(tok.alphabet)), tok.merges)
    changed_tokenizer = ck.input_signature(changed_tok, text)
    changed_source = copy.deepcopy(identity)
    changed_source['source_sha256']['model.py'] = '0' * 64
    cases = [('matching bundle', ROOT / 'best.json', identity),
             ('changed corpus', ROOT / 'best.json', changed_corpus),
             ('same-size tokenizer with different IDs', ROOT / 'best.json', changed_tokenizer),
             ('changed implementation', ROOT / 'best.json', changed_source)]
    results = []
    with tempfile.TemporaryDirectory() as work:
        old = ck.load(ROOT / 'best.json', t.CONFIG)
        old.pop('training_inputs')
        missing = Path(work) / 'missing.json'
        ck.save(missing, old)
        cases.append(('missing input identity', missing, identity))
        for name, path, expected in cases:
            try:
                ck.load(path, t.CONFIG, expected)
                results.append({'case': name, 'accepted': True})
            except ValueError as error:
                results.append({'case': name, 'accepted': False, 'error': str(error)})
    return results


if __name__ == '__main__':
    output = json.dumps(inspect(), indent=2) + '\n'
    if '--check' in sys.argv:
        if output != (ROOT / 'input-checks.json').read_text():
            raise SystemExit('input identity results differ from input-checks.json')
    else:
        print(output, end='')
