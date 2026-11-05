"""A local HTTP boundary for bounded scripted documentation retrieval."""
from contextlib import asynccontextmanager
import json
import hashlib
from fastapi import FastAPI,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from tools import DocumentationTools,load_snapshot
from service import RetrieveRequest,retrieve

MAX_BODY_BYTES=4096

def error_body(code,issues=None):
    body={'error':{'code':code},'admission':{'accepted':False}}
    if issues is not None:body['error']['issues']=issues
    return body

def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate_key')
            result[key]=value
        return result
    def invalid(value):raise ValueError('invalid_constant')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=invalid)

class BoundedJSONBody:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method']!='POST' or scope['path']!='/retrieve':
            return await self.app(scope,receive,send)
        headers=dict(scope['headers']);media=headers.get(b'content-type',b'').split(b';',1)[0].strip().lower()
        if media!=b'application/json':return await JSONResponse(error_body('unsupported_media_type'),415)(scope,receive,send)
        raw=bytearray()
        while True:
            message=await receive()
            if message['type']=='http.disconnect':return
            piece=message.get('body',b'')
            if len(raw)+len(piece)>MAX_BODY_BYTES:return await JSONResponse(error_body('body_too_large'),413)(scope,receive,send)
            raw.extend(piece)
            if not message.get('more_body',False):break
        try:strict_json(bytes(raw))
        except (ValueError,UnicodeError,RecursionError):return await JSONResponse(error_body('invalid_json'),422)(scope,receive,send)
        delivered=False
        async def replay():
            nonlocal delivered
            if delivered:return await receive()
            delivered=True;return {'type':'http.request','body':bytes(raw),'more_body':False}
        return await self.app(scope,replay,send)

def create_app(tool_factory=DocumentationTools):
    @asynccontextmanager
    async def lifespan(app):
        app.state.snapshot=load_snapshot();app.state.ready=True
        try:yield
        finally:app.state.ready=False;app.state.snapshot=None
    app=FastAPI(title='Local documentation retrieval',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.ready=False;app.state.snapshot=None
    app.add_middleware(BoundedJSONBody)
    @app.exception_handler(RequestValidationError)
    async def validation_error(request,error):
        issues=[{'path':[str(part)[:64] for part in issue['loc'][:6]],'type':issue['type']} for issue in error.errors()[:12]]
        return JSONResponse(error_body('invalid_request',issues),422)
    @app.exception_handler(Exception)
    async def unexpected_error(request,error):return JSONResponse(error_body('internal_error'),500)
    @app.get('/health')
    def health():
        if not app.state.ready:return JSONResponse({'status':'not_ready'},503)
        return {'status':'ok','mode':'offline-scripted-retrieval','corpus_id':app.state.snapshot['snapshot_id']}
    @app.post('/retrieve')
    def retrieve_endpoint(payload:RetrieveRequest,request:Request):
        if not app.state.ready:return JSONResponse(error_body('not_ready'),503)
        code,body=retrieve(payload,app.state.snapshot,tool_factory)
        response=JSONResponse(body,code)
        response.headers['X-Retrieval-Body-SHA256']=hashlib.sha256(response.body).hexdigest()
        return response
    return app

app=create_app()
