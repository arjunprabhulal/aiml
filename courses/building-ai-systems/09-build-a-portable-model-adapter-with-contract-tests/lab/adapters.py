"""One chat contract, two wire formats: Ollama's native /api/chat and the OpenAI-compatible
/v1/chat/completions. Application code depends on ChatRequest, ChatResult and AdapterError only.
Python 3.11+, standard library only.

python3 adapters.py --api openai-compatible "What does JSON stand for?"
"""
import argparse
import json
import math
import socket
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROLES = ('system', 'user', 'assistant')
FINISH = ('stop', 'length')
KINDS = ('connection', 'timeout', 'model_not_found', 'http', 'protocol', 'unsupported')


class AdapterError(RuntimeError):
    """A failure in one of the six kinds the contract names. No adapter retries."""

    def __init__(self, kind, message):
        assert kind in KINDS
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ChatRequest:
    messages: tuple
    max_tokens: int = 64
    temperature: float = 0.0
    seed: int | None = 42
    context_tokens: int | None = None


@dataclass(frozen=True)
class ChatResult:
    text: str
    finish: str
    input_tokens: int
    output_tokens: int


def validate(request):
    """The request half of the contract. Runs before any adapter builds a body."""
    messages = request.messages
    if not isinstance(messages, tuple) or not messages:
        raise ValueError('messages must be a nonempty tuple of (role, content) pairs.')
    for index, item in enumerate(messages):
        if not (isinstance(item, tuple) and len(item) == 2 and item[0] in ROLES
                and isinstance(item[1], str) and item[1].strip()):
            raise ValueError(f'Message {index} must be (role, text) with a known role and nonblank text.')
        if item[0] == 'system' and index != 0:
            raise ValueError('Only the first message may be a system message.')
    if messages[-1][0] != 'user':
        raise ValueError('The last message must come from the user.')
    if type(request.max_tokens) is not int or not 1 <= request.max_tokens <= 4096:
        raise ValueError('max_tokens must be an integer from 1 to 4096.')
    if (isinstance(request.temperature, bool) or not isinstance(request.temperature, (int, float))
            or not 0 <= request.temperature <= 2):
        raise ValueError('temperature must be a number from 0 to 2.')
    if request.seed is not None and type(request.seed) is not int:
        raise ValueError('seed must be an integer or None.')
    if request.context_tokens is not None and (type(request.context_tokens) is not int
                                               or request.context_tokens < 256):
        raise ValueError('context_tokens must be an integer of at least 256, or None.')


def http_post(url, payload, headers, timeout):
    """Send one JSON POST. Returns (status, body bytes); raises only for transport failures."""
    request = Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()
    except (TimeoutError, socket.timeout) as error:
        raise AdapterError('timeout', 'The model server did not answer in time. No retry was sent.') from error
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise AdapterError('timeout', 'The model server did not answer in time. No retry was sent.') from error
        raise AdapterError('connection', f'Cannot reach the model server: {error.reason}') from error
    except ConnectionError as error:
        raise AdapterError('connection', f'Cannot reach the model server: {error}') from error


def local_origin(base_url):
    url = urlsplit(base_url)
    if url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('These adapters accept only a local HTTP model server.')
    if url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        raise ValueError('Use a server origin without credentials or a path.')
    return base_url.rstrip('/')


def decode(status, body):
    """Shared status and JSON handling. Each adapter then reads its own response shape."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError):
        data = None
    if status == 404:
        raise AdapterError('model_not_found', 'The server does not have this model. Pull it explicitly.')
    if status != 200:
        raise AdapterError('http', f'The model server returned HTTP {status}.')
    if not isinstance(data, dict):
        raise AdapterError('protocol', 'The response body is not a JSON object.')
    return data


def count(value, name):
    if type(value) is not int or value < 0:
        raise AdapterError('protocol', f'Missing or invalid token count: {name}.')
    return value


def result(text, finish, input_tokens, output_tokens):
    """The result half of the contract, shared so both adapters accept exactly the same results."""
    if not isinstance(text, str) or not text.strip():
        raise AdapterError('protocol', 'The reply has no text. Check that thinking is turned off.')
    if finish not in FINISH:
        raise AdapterError('protocol', f'Unsupported finish reason: {finish!r}.')
    return ChatResult(text.strip(), finish, input_tokens, output_tokens)


class OllamaChatAdapter:
    """Ollama's native API: POST /api/chat."""
    name = 'ollama-native'
    path = '/api/chat'

    def __init__(self, base_url='http://127.0.0.1:11434', post=http_post, timeout=120):
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Timeout must be positive and finite.')
        self.base_url, self.post, self.timeout = local_origin(base_url), post, timeout

    def body(self, model, request):
        options = {'num_predict': request.max_tokens, 'temperature': request.temperature}
        if request.seed is not None:
            options['seed'] = request.seed
        if request.context_tokens is not None:
            options['num_ctx'] = request.context_tokens
        return {'model': model, 'messages': [{'role': r, 'content': c} for r, c in request.messages],
                'stream': False, 'think': False, 'options': options}

    def parse(self, status, body):
        data = decode(status, body)
        message = data.get('message')
        if data.get('done') is not True or not isinstance(message, dict) or message.get('role') != 'assistant':
            raise AdapterError('protocol', 'Expected a completed assistant message.')
        if message.get('tool_calls'):
            raise AdapterError('protocol', 'The reply asks for a tool call; this contract has none.')
        return result(message.get('content'), data.get('done_reason'),
                      count(data.get('prompt_eval_count'), 'prompt_eval_count'),
                      count(data.get('eval_count'), 'eval_count'))

    def complete(self, model, request):
        validate(request)
        status, body = self.post(self.base_url + self.path, self.body(model, request),
                                 {'Content-Type': 'application/json'}, self.timeout)
        return self.parse(status, body)


class OpenAICompatibleAdapter(OllamaChatAdapter):
    """The OpenAI-compatible API that Ollama also serves: POST /v1/chat/completions."""
    name = 'openai-compatible'
    path = '/v1/chat/completions'

    def body(self, model, request):
        if request.context_tokens is not None:
            raise AdapterError('unsupported', 'This API cannot set the context size; leave context_tokens unset.')
        body = {'model': model, 'messages': [{'role': r, 'content': c} for r, c in request.messages],
                'max_tokens': request.max_tokens, 'temperature': request.temperature,
                'stream': False, 'reasoning_effort': 'none'}
        if request.seed is not None:
            body['seed'] = request.seed
        return body

    def parse(self, status, body):
        data = decode(status, body)
        choices = data.get('choices')
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise AdapterError('protocol', 'Expected exactly one choice.')
        message, usage = choices[0].get('message'), data.get('usage')
        if not isinstance(message, dict) or message.get('role') != 'assistant' or not isinstance(usage, dict):
            raise AdapterError('protocol', 'Expected an assistant message and a usage object.')
        if message.get('tool_calls'):
            raise AdapterError('protocol', 'The reply asks for a tool call; this contract has none.')
        return result(message.get('content'), choices[0].get('finish_reason'),
                      count(usage.get('prompt_tokens'), 'prompt_tokens'),
                      count(usage.get('completion_tokens'), 'completion_tokens'))


ADAPTERS = {adapter.name: adapter for adapter in (OllamaChatAdapter, OpenAICompatibleAdapter)}


def main():
    parser = argparse.ArgumentParser(description='Ask one question through either adapter.')
    parser.add_argument('question')
    parser.add_argument('--api', choices=sorted(ADAPTERS), default='ollama-native')
    parser.add_argument('--model', default='gemma4:e2b')
    parser.add_argument('--base-url', default='http://127.0.0.1:11434')
    parser.add_argument('--max-tokens', type=int, default=64)
    args = parser.parse_args()
    request = ChatRequest((('system', 'Answer in one short sentence.'), ('user', args.question)),
                          max_tokens=args.max_tokens)
    try:
        reply = ADAPTERS[args.api](args.base_url).complete(args.model, request)
    except (ValueError, AdapterError) as error:
        kind = getattr(error, 'kind', 'request')
        parser.exit(1, f'{kind}: {error}\n')
    print(json.dumps(reply.__dict__, ensure_ascii=False))


if __name__ == '__main__':
    main()
