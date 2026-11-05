"""Capped Gemini JSON decisions and exact-request offline replay. No retries."""
import copy
import json
import os
import ssl
import urllib.error
import urllib.request

MODEL = 'gemini-3.8-flash'
ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/' + MODEL + ':generateContent'
CONFIG = {'maxOutputTokens': 1024, 'temperature': 0,
          'thinkingConfig': {'thinkingLevel': 'LOW'}, 'responseMimeType': 'application/json'}


def payload(messages, schema):
    return {'systemInstruction': {'parts': [{'text': messages[0]['content']}]},
            'contents': [{'role': 'user', 'parts': [{'text': messages[1]['content']}]}],
            'generationConfig': {**CONFIG, 'responseJsonSchema': schema}}


def decode(response):
    candidates = response.get('candidates', [])
    if len(candidates) != 1 or candidates[0].get('finishReason') != 'STOP':
        raise RuntimeError('unfinished_model_reply')
    text = ''.join(p.get('text', '') for p in candidates[0].get('content', {}).get('parts', []) if not p.get('thought'))
    return json.loads(text)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Allowance:
    def __init__(self, limit=200):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('invalid_request_allowance')
        self.limit, self.used = limit, 0


class Gemini:
    def __init__(self, allowance, save=None):
        self.allowance, self.save, self.records = allowance, save, []

    def decide(self, messages, schema, timeout=45):
        body = payload(messages, schema)
        raw = json.dumps(body).encode()
        if len(raw) > 30000:
            raise RuntimeError('provider_input_bytes_limit')
        if self.allowance.used >= self.allowance.limit:
            raise RuntimeError('batch_request_limit')
        key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
        if not key:
            raise RuntimeError('missing_api_key')
        # Credentials are only headers; headers never enter the recording.
        request = urllib.request.Request(ENDPOINT, data=raw, method='POST',
            headers={'Content-Type': 'application/json', 'x-goog-api-key': key})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self.allowance.used += 1
        record = {'request': copy.deepcopy(body)}
        try:
            with opener.open(request, timeout=timeout) as response:
                output = response.read(262145)
                if len(output) > 262144:
                    raise RuntimeError('provider_response_bytes_limit')
                record['response'] = json.loads(output)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            record['error'] = type(error).__name__
            if isinstance(error, urllib.error.HTTPError):
                record['http_status'] = error.code
            raise RuntimeError('model_transport_failed:' + record['error']) from None
        finally:
            self.records.append(record)
            if self.save:
                self.save(copy.deepcopy(self.records))
        return decode(record['response'])


class ReplayModel:
    def __init__(self, records):
        self.records, self.index = copy.deepcopy(records), 0

    def decide(self, messages, schema, timeout=45):
        if self.index >= len(self.records):
            raise RuntimeError('replay_exhausted')
        record = self.records[self.index]
        if record['request'] != payload(messages, schema):
            raise RuntimeError('replay_request_mismatch')
        self.index += 1
        if 'error' in record:
            raise RuntimeError('model_transport_failed:' + record['error'])
        return decode(record['response'])
