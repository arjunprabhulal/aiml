"""Ask the pinned Gemma 4 E2B model through a local Ollama server, and record the answers.

Only the recording step calls the server. The tests grade the recorded
answers again and never call a model. A few answers from a small model are
an illustration of how a request behaves, not a measure of answer quality.
"""
import json
from pathlib import Path
from urllib import error, request

HERE = Path(__file__).parent
MODEL = json.loads((HERE / 'answer-model.json').read_text())


class AnswerModelError(RuntimeError):
    pass


def http_transport(base_url: str = 'http://127.0.0.1:11434', timeout: float = 300):
    def call(path: str, payload: dict | None) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        req = request.Request(base_url + path, data=data, headers={'Content-Type': 'application/json'})
        try:
            with request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except error.HTTPError as failure:
            raise AnswerModelError(f'{path} returned HTTP {failure.code}: {failure.read().decode(errors="replace")[:200]}') from None
    return call


def for_ollama(messages: list[dict]) -> list[dict]:
    """Ollama takes tool-call arguments as an object, not the JSON string chat APIs use."""
    out = []
    for m in messages:
        if m.get('tool_calls'):
            m = {**m, 'tool_calls': [{'function': {'name': c['function']['name'],
                                                   'arguments': json.loads(c['function']['arguments'])}}
                                     for c in m['tool_calls']]}
        out.append({k: v for k, v in m.items() if k in ('role', 'content', 'tool_calls')})
    return out


class AnswerModel:
    def __init__(self, transport=None):
        self.call = transport or http_transport()
        models = {m['name']: m['digest'] for m in self.call('/api/tags', None).get('models', [])}
        if models.get(MODEL['ollama_tag']) != MODEL['ollama_digest']:
            raise AnswerModelError(f"{MODEL['ollama_tag']} is missing or not the pinned digest; "
                                   f"run: ollama pull {MODEL['ollama_tag']}")

    def answer(self, messages: list[dict], tools: list[dict], num_ctx: int, num_predict: int, seed: int) -> dict:
        response = self.call('/api/chat', {
            'model': MODEL['ollama_tag'], 'messages': for_ollama(messages), 'tools': tools or None,
            'stream': False, 'think': MODEL['think'],
            'options': {**MODEL['options'], 'seed': seed, 'num_ctx': num_ctx, 'num_predict': num_predict}})
        message = response.get('message', {})
        return {'seed': seed, 'answer': message.get('content', ''),
                'tool_calls': [c['function']['name'] for c in message.get('tool_calls') or []],
                'done_reason': response.get('done_reason'), 'prompt_tokens': response.get('prompt_eval_count'),
                'answer_tokens': response.get('eval_count')}
