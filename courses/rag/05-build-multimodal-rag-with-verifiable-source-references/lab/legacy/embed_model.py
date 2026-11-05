"""Embed text with a pinned local Qwen3-Embedding model, or replay recorded vectors. Python 3.11+.

Queries carry the model card's one-sentence instruction; figure documents
do not. Truncation is off, so an input longer than the context fails. In
replay mode no connection is opened: a vector that was never recorded is an error.
"""
from array import array
import base64
import hashlib
import json
import math
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOCAL_SERVER = 'http://127.0.0.1:11434'
NORM_TOLERANCE = 1e-3


class EmbedError(RuntimeError):
    pass


def _post(path, payload=None, timeout=120):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(LOCAL_SERVER + path, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        raise EmbedError(f'Embedding server returned HTTP {error.code}.') from error
    except (URLError, TimeoutError) as error:
        raise EmbedError('Cannot reach the local model server on 127.0.0.1:11434.') from error


def query_text(manifest, query):
    """The model card's query format: a task instruction, then the query."""
    return f'Instruct: {manifest["query_instruction"]}\nQuery:{query}'


def _pack(vector):
    """Store the vector exactly: 64-bit floats, little-endian, base64. JSON text would be 2x larger."""
    packed = array('d', vector)
    if packed.itemsize != 8 or packed.tolist() != vector:
        raise EmbedError('The vector does not round-trip through 64-bit floats.')
    if sys.byteorder != 'little':
        packed.byteswap()
    return base64.b64encode(packed.tobytes()).decode()


def _unpack(text):
    values = array('d')
    values.frombytes(base64.b64decode(text))
    if sys.byteorder != 'little':
        values.byteswap()
    return values.tolist()


class Embedder:
    def __init__(self, manifest, recordings_path, mode='replay'):
        if mode not in ('replay', 'record'):
            raise ValueError('mode must be replay or record.')
        self.manifest, self.mode, self.path = manifest, mode, Path(recordings_path)
        self.recordings = json.loads(self.path.read_text()) if self.path.exists() else {}
        if mode == 'record':
            models = {m.get('name'): m.get('digest') for m in _post('/api/tags').get('models', [])}
            if models.get(manifest['ollama_tag']) != manifest['ollama_digest']:
                raise EmbedError(f'{manifest["ollama_tag"]} is missing or not the pinned digest. Stop.')

    def _embed(self, text):
        if not isinstance(text, str) or not text.strip():
            raise EmbedError('Every input must be nonblank text.')
        key = hashlib.sha256(json.dumps({'digest': self.manifest['ollama_digest'], 'text': text}).encode()).hexdigest()
        if key not in self.recordings:
            if self.mode == 'replay':
                raise EmbedError(f'No recorded vector for input {key[:12]}. Run in record mode with Ollama.')
            response = _post('/api/embed', {'model': self.manifest['ollama_tag'], 'input': [text], 'truncate': False})
            vectors = response.get('embeddings')
            if not isinstance(vectors, list) or len(vectors) != 1:
                raise EmbedError('Expected exactly one vector.')
            self.recordings[key] = {'vector': _pack(vectors[0]), 'tokens': response.get('prompt_eval_count')}
            self.path.write_text(json.dumps(self.recordings, indent=1, sort_keys=True) + '\n')
        vector = _unpack(self.recordings[key]['vector'])
        if len(vector) != self.manifest['dimensions']:
            raise EmbedError(f'Expected {self.manifest["dimensions"]} dimensions, got {len(vector)}.')
        if abs(math.sqrt(math.fsum(x * x for x in vector)) - 1) > NORM_TOLERANCE:
            raise EmbedError('Expected a unit-length vector.')
        return vector

    def document(self, text):
        return self._embed(text)

    def query(self, text):
        return self._embed(query_text(self.manifest, text))
