"""Bounded Gemini REST transport. Offline imports never load credentials."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

MODEL = 'gemini-3.1-flash-lite'
CONFIG = {'temperature': 0, 'maxOutputTokens': 2048, 'candidateCount': 1,
          'thinkingConfig': {'thinkingLevel': 'minimal'}, 'responseMimeType': 'application/json'}
ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/' + MODEL
RESERVATION_USD = 0.10
MAX_REQUESTS = 80
MAX_INPUT_BYTES = 60000
PRICE = {'input_per_million_usd': 0.25, 'output_including_thinking_per_million_usd': 1.50,
         'checked': '2026-10-24', 'source': 'https://ai.google.dev/gemini-api/docs/pricing'}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def reserve(path, request_hash):
    """Reserve before opening network; errors keep their reservation. Shared process lock."""
    path=Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        file.seek(0); raw=file.read()
        ledger=json.loads(raw) if raw else {'cap_usd': 10, 'reservations': []}
        if ledger.get('cap_usd') != 10 or not isinstance(ledger.get('reservations'), list):
            raise ValueError('invalid_budget_ledger')
        if len(ledger['reservations']) >= MAX_REQUESTS: raise ValueError('budget_exhausted')
        ledger['reservations'].append({'request_sha256': request_hash, 'reserved_usd': RESERVATION_USD})
        ledger['reserved_usd']=round(len(ledger['reservations'])*RESERVATION_USD, 2)
        file.seek(0);file.truncate();json.dump(ledger,file,indent=2);file.flush();os.fsync(file.fileno())
        return len(ledger['reservations'])

def text_of(response):
    candidates=response.get('candidates', [])
    if len(candidates)!=1: raise ValueError('missing_candidate')
    return ''.join(p.get('text','') for p in candidates[0].get('content',{}).get('parts',[]) if not p.get('thought'))

def finish_of(response):
    return response.get('candidates',[{}])[0].get('finishReason') if response.get('candidates') else None

def usage_cost(response):
    usage=response.get('usageMetadata',{})
    inputs=usage.get('promptTokenCount',0)
    outputs=usage.get('candidatesTokenCount',0)+usage.get('thoughtsTokenCount',0)
    return (inputs*PRICE['input_per_million_usd']+outputs*PRICE['output_including_thinking_per_million_usd'])/1000000

class Gemini:
    def __init__(self, ledger, directory):
        self.ledger=Path(ledger);self.directory=Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.calls=[]
    def request(self, system, user, *, stream=False, schema=None):
        payload={'systemInstruction':{'parts':[{'text':system}]},
                 'contents':[{'role':'user','parts':[{'text':user}]}],
                 'generationConfig':dict(CONFIG)}
        if schema is not None: payload['generationConfig']['responseJsonSchema']=schema
        wire=json.dumps(payload,ensure_ascii=False).encode()
        if len(wire)>MAX_INPUT_BYTES: raise ValueError('request_byte_limit')
        request_hash=digest(payload)
        number=reserve(self.ledger,request_hash)
        # No key lookup before configuration, input-size and spending checks.
        key=os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
        if not key: raise ValueError('missing_gemini_credential')
        record={'model':MODEL,'request':payload,'request_sha256':request_hash,'stream':stream,
                'reservation_number':number,'reserved_usd':RESERVATION_USD,'price':PRICE,
                'seed':'not set; provider default','retries':0,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'responses':[]}
        path=self.directory/f'request-{number:03d}.json'
        path.write_text(json.dumps(record,indent=2)+'\n')
        request=urllib.request.Request(ENDPOINT+(':streamGenerateContent?alt=sse' if stream else ':generateContent'),
            data=wire,headers={'Content-Type':'application/json','x-goog-api-key':key})
        started=time.monotonic()
        try:
            with urllib.request.urlopen(request,timeout=90) as response:
                if stream:
                    for event in sse_json(response):
                        record['responses'].append({'elapsed_ms':round((time.monotonic()-started)*1000,3),'payload':event})
                        path.write_text(json.dumps(record,indent=2)+'\n')
                        yield event
                else:
                    event=json.loads(response.read(524289))
                    record['responses'].append({'elapsed_ms':round((time.monotonic()-started)*1000,3),'payload':event})
                    yield event
        except Exception as error:
            record['error']={'type':type(error).__name__,'http_status':getattr(error,'code',None)}
            raise
        finally:
            record['elapsed_ms']=round((time.monotonic()-started)*1000,3)
            record['estimated_usd']=usage_cost(record['responses'][-1]['payload']) if record['responses'] else None
            path.write_text(json.dumps(record,indent=2)+'\n')
            self.calls.append({'file':path.name,'request_sha256':request_hash,'estimated_usd':record['estimated_usd']})
    def generate(self,system,user,schema=None):
        response=list(self.request(system,user,schema=schema))[0]
        if finish_of(response)!='STOP': raise ValueError('provider_did_not_finish')
        return json.loads(text_of(response))

def sse_json(lines):
    """Parse multiline SSE data; EOF inside an event is not completion."""
    data=[];total=0
    for line in lines:
        total+=len(line)
        if total>524288 or len(line)>131072: raise ValueError('provider_stream_byte_limit')
        text=line.decode('utf-8').rstrip('\r\n')
        if not text:
            if data:
                yield json.loads('\n'.join(data));data=[]
        elif text.startswith('data:'):
            data.append(text[5:].lstrip(' '))
    if data: raise ValueError('truncated_provider_event')
