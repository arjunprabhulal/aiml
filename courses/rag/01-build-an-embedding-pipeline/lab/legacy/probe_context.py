"""Check that an input longer than the model's context is refused, not truncated.

    python probe_context.py   # needs the Ollama server; writes context-probe.json

Two inputs are built by joining corpus passages in order, using the token
count index.json records for each passage: one that stays under the model's
context length and one that exceeds it. Both are sent with truncate: false.
"""
import json
from pathlib import Path
from embedder import MANIFEST, Embedder, EmbeddingError

HERE = Path(__file__).parent
UNDER, OVER = 25_000, 40_000


def joined(passages: list[dict], tokens: list[int], target: int, above: bool) -> tuple[str, int]:
    """Join passages until their recorded tokens reach the target (above) or stay just under it."""
    texts, total = [], 0
    for passage, count in zip(passages, tokens):
        if not above and total + count > target:
            break
        texts.append(passage['text'])
        total += count
        if above and total >= target:
            break
    return '\n\n'.join(texts), len(texts)


def probe() -> dict:
    index = json.loads((HERE / 'index.json').read_text())
    passages = json.loads((HERE / 'corpus.json').read_text())['passages']
    embedder = Embedder()
    results = []
    for target, above in ((UNDER, False), (OVER, True)):
        text, count = joined(passages, index['tokens'], target, above)
        row = {'passages_joined': count, 'recorded_tokens_of_those_passages': sum(index['tokens'][:count])}
        try:
            row.update({'outcome': 'embedded', 'server_tokens': embedder.tokens(text)})
        except EmbeddingError as error:
            row.update({'outcome': 'refused', 'error': str(error)})
        results.append(row)
    return {'model': MANIFEST['ollama_tag'], 'model_digest': MANIFEST['ollama_digest'],
            'context_length': MANIFEST['context_length'], 'truncate': False, 'inputs': results}


if __name__ == '__main__':
    (HERE / 'context-probe.json').write_text(json.dumps(probe(), indent=2) + '\n')
