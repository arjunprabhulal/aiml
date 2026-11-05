"""Ask the pinned local vision model a question with text and images, or replay the answer. Python 3.11+.

record mode checks the digest and the vision capability, then calls
/api/chat with a JSON schema in `format`. replay mode never opens a
connection; a request that was never recorded is an error.
"""
import base64
import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pngio import encode_png

LOCAL_SERVER = 'http://127.0.0.1:11434'


class ModelError(RuntimeError):
    pass


def _post(path, payload=None, timeout=600):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(LOCAL_SERVER + path, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        raise ModelError(f'Model server returned HTTP {error.code}.') from error
    except (URLError, TimeoutError) as error:
        raise ModelError('Cannot reach the local model server on 127.0.0.1:11434.') from error


class AnswerModel:
    def __init__(self, manifest, options, recordings_path, mode='replay'):
        if mode not in ('replay', 'record'):
            raise ValueError('mode must be replay or record.')
        self.manifest, self.options, self.mode, self.path = manifest, options, mode, Path(recordings_path)
        self.recordings = json.loads(self.path.read_text()) if self.path.exists() else {}
        if mode == 'record':
            installed = {m.get('name'): m.get('digest') for m in _post('/api/tags').get('models', [])}
            if installed.get(manifest['ollama_tag']) != manifest['ollama_digest']:
                raise ModelError('The installed model digest differs from model-manifest.json. Stop.')
            if 'vision' not in _post('/api/show', {'model': manifest['ollama_tag']}).get('capabilities', []):
                raise ModelError('The installed model does not report the vision capability.')

    def key(self, system, user, images, schema):
        material = {'digest': self.manifest['ollama_digest'], 'system': system, 'user': user,
                    'images': [image.sha256() for image in images], 'schema': schema, 'options': self.options}
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def chat(self, system, user, images, schema):
        """Return {'text', 'done_reason', 'prompt_tokens', 'output_tokens', 'total_ms'}."""
        key = self.key(system, user, images, schema)
        if key in self.recordings:
            return self.recordings[key]
        if self.mode == 'replay':
            raise ModelError(f'No recorded answer for request {key[:12]}. Run in record mode with Ollama.')
        options = {k: v for k, v in self.options.items() if k != 'think'}
        message = {'role': 'user', 'content': user}
        if images:
            message['images'] = [base64.b64encode(encode_png(image)).decode() for image in images]
        payload = {'model': self.manifest['ollama_tag'], 'stream': False, 'think': self.options['think'],
                   'options': options, 'messages': [{'role': 'system', 'content': system}, message]}
        if schema is not None:
            payload['format'] = schema
        started = time.perf_counter()
        response = _post('/api/chat', payload)
        reply = response.get('message') or {}
        if response.get('done') is not True or not isinstance(reply.get('content'), str):
            raise ModelError('Expected one completed, non-streaming chat response.')
        answer = {'text': reply['content'], 'done_reason': response.get('done_reason'),
                  'prompt_tokens': response.get('prompt_eval_count'), 'output_tokens': response.get('eval_count'),
                  'total_ms': round((time.perf_counter() - started) * 1000)}
        self.recordings[key] = answer
        self.path.write_text(json.dumps(self.recordings, indent=1, sort_keys=True) + '\n')
        return answer
