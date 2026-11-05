"""Loopback teaching service; token grants are configured by the server."""
from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import hmac
import json
import os
from threading import Lock
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from assistant import Assistant, Ask, BadAnswer, Busy, Denied, terms
from providers import Gemini

ROOT = Path(__file__).parent

def create_app(service=None, tokens=None):
    tokens = tokens or {os.environ.get('DOCS_READER_TOKEN','reader-demo-token'):('demo-reader','reader'),
        os.environ.get('DOCS_MAINTAINER_TOKEN','maintainer-demo-token'):('demo-maintainer','maintainer')}
    if len(tokens)!=2: raise ValueError('Use distinct reader and maintainer tokens')
    @asynccontextmanager
    async def lifespan(app):
        def record(response):
            folder=os.environ.get('CAPSTONE_RECORD_DIR')
            if folder:
                target=Path(folder);target.mkdir(parents=True,exist_ok=True)
                index=len(list(target.glob('response-*.json')))+1
                def public_projection(value):
                    if isinstance(value,dict):return {k:public_projection(v) for k,v in value.items() if k not in {'thoughtSignature','thought_signature'}}
                    if isinstance(value,list):return [public_projection(v) for v in value]
                    return value
                (target/f'response-{index:02}.json').write_text(json.dumps(public_projection(response),indent=2)+'\n')
        app.state.assistant = service or Assistant(provider=Gemini(record=record) if os.environ.get('CAPSTONE_PROVIDER')=='gemini' else None)
        yield
        app.state.assistant = None
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    def identity(request):
        value = request.headers.get('authorization','')
        if not value.startswith('Bearer '): raise Denied('Authentication required')
        token = value[7:]
        for candidate, principal in tokens.items():
            if hmac.compare_digest(token.encode(), candidate.encode()): return principal
        raise Denied('Authentication required')
    @app.get('/')
    def home(): return FileResponse(ROOT/'static/index.html.template', media_type='text/html')
    @app.get('/app.js')
    def script(): return FileResponse(ROOT/'static/app.js', media_type='text/javascript')
    @app.get('/style.css')
    def style(): return FileResponse(ROOT/'static/style.css', media_type='text/css')
    @app.get('/health')
    def health(): return {'status':'ok','provider':app.state.assistant.provider.name,'snapshot':app.state.assistant.corpus.snapshot}
    @app.get('/api/sources/{document_id}')
    def source(document_id:str,request:Request):
        try:
            _,role = identity(request)
            return app.state.assistant.corpus.document(role,document_id)
        except Denied: return JSONResponse({'error':'Source unavailable'},status_code=403)
    @app.post('/api/ask')
    async def ask(request:Request):
        try: principal, role = identity(request)
        except Denied: return JSONResponse({'error':'Authentication required'},status_code=401)
        body = bytearray()
        async for chunk in request.stream():
            if len(body)+len(chunk)>4096: return JSONResponse({'error':'Request body too large'},status_code=413)
            body.extend(chunk)
        try:
            def unique(pairs):
                result={}
                for k,v in pairs:
                    if k in result: raise ValueError('Duplicate JSON key')
                    result[k]=v
                return result
            data=json.loads(body.decode('utf-8'),object_pairs_hook=unique)
            query=Ask.model_validate(data)
            if not terms(query.question): raise ValueError('Empty question')
        except (ValidationError,ValueError,UnicodeError): return JSONResponse({'error':'Invalid question, version or collection'},status_code=422)
        try:
            return await asyncio.to_thread(app.state.assistant.ask,principal,role,query)
        except Denied: return JSONResponse({'error':'Collection access denied'},status_code=403)
        except Busy: return JSONResponse({'error':'Assistant is busy; try later'},status_code=429)
        except (BadAnswer,RuntimeError,OSError,ValueError): return JSONResponse({'error':'Answer generation failed; no answer accepted'},status_code=502)
    return app

app = create_app()
