"""Embed passages and queries with Qwen3-Embedding-0.6B served by a local Ollama.

Standard library only. The adapter checks that the server runs the pinned
model digest, sends documents without an instruction and queries with the
one-sentence instruction the model card recommends, refuses silent
truncation, and checks every returned vector's length and dimension.
"""
from collections.abc import Callable
import json
import math
from pathlib import Path
import urllib.error
import urllib.request

MANIFEST = json.loads(Path(__file__).with_name('model-manifest.json').read_text())
NORM_TOLERANCE = 1e-3

Transport = Callable[[str, dict | None], dict]


class EmbeddingError(RuntimeError):
    """The server, the model or a returned vector does not match the manifest."""


def http_transport(base_url: str = 'http://127.0.0.1:11434', timeout: float = 120) -> Transport:
    def call(path: str, payload: dict | None) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(base_url + path, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise EmbeddingError(f'{path} returned HTTP {error.code}: {error.read().decode(errors="replace")[:200]}') from None
        except (urllib.error.URLError, TimeoutError) as error:
            raise EmbeddingError(f'cannot reach the model server: {error}') from None
    return call


def query_text(query: str) -> str:
    """The model card's query format: a task instruction, then the query."""
    return f'Instruct: {MANIFEST["query_instruction"]}\nQuery:{query}'


class Embedder:
    def __init__(self, transport: Transport | None = None):
        self.call = transport or http_transport()
        models = {m['name']: m['digest'] for m in self.call('/api/tags', None).get('models', [])}
        if models.get(MANIFEST['ollama_tag']) != MANIFEST['ollama_digest']:
            raise EmbeddingError(f'{MANIFEST["ollama_tag"]} is missing or not the pinned digest; '
                                 f'run: ollama pull {MANIFEST["ollama_tag"]}')

    def _embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise EmbeddingError('every input must be nonblank text')
        response = self.call('/api/embed', {'model': MANIFEST['ollama_tag'], 'input': texts, 'truncate': False})
        vectors = response.get('embeddings')
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingError(f'expected {len(texts)} vectors, got {len(vectors) if isinstance(vectors, list) else 0}')
        for vector in vectors:
            if len(vector) != MANIFEST['dimensions']:
                raise EmbeddingError(f'expected {MANIFEST["dimensions"]} dimensions, got {len(vector)}')
            norm = math.sqrt(sum(x * x for x in vector))
            if abs(norm - 1) > NORM_TOLERANCE:
                raise EmbeddingError(f'expected a unit-length vector, got length {norm:.4f}')
        return vectors, response.get('prompt_eval_count', 0)

    def documents(self, texts: list[str], batch_size: int = 16) -> tuple[list[list[float]], list[int]]:
        """Embed passages in batches. Returns vectors in input order and the token count of each batch."""
        if type(batch_size) is not int or batch_size < 1:
            raise EmbeddingError('batch_size must be a positive integer')
        if not texts:
            raise EmbeddingError('no passages to embed')
        vectors, tokens = [], []
        for start in range(0, len(texts), batch_size):
            batch, count = self._embed(texts[start:start + batch_size])
            vectors += batch
            tokens.append(count)
        return vectors, tokens

    def query(self, query: str, instruction: bool = True) -> list[float]:
        return self._embed([query_text(query) if instruction else query])[0][0]

    def tokens(self, text: str) -> int:
        """Tokens the model processed for one input, as the server reports them."""
        return self._embed([text])[1]
