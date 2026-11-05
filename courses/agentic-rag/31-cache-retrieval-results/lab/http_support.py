"""Bounded local JSON body boundary, adapted from Module 10 middleware."""
import json
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

def error(code,status):return JSONResponse({'error':{'code':code}},status)
def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate_key')
            result[key]=value
        return result
    def invalid(value):raise ValueError('nonfinite')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=invalid)
class BoundedJSONBody:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method']!='POST':return await self.app(scope,receive,send)
        media=dict(scope['headers']).get(b'content-type',b'').split(b';',1)[0].strip().lower()
        if media!=b'application/json':return await error('unsupported_media_type',415)(scope,receive,send)
        raw=bytearray()
        while True:
            msg=await receive()
            if msg['type']=='http.disconnect':return
            piece=msg.get('body',b'')
            if len(raw)+len(piece)>8192:return await error('body_too_large',413)(scope,receive,send)
            raw.extend(piece)
            if not msg.get('more_body',False):break
        try:strict_json(bytes(raw))
        except (ValueError,UnicodeError,RecursionError):return await error('invalid_json',422)(scope,receive,send)
        delivered=False
        async def replay():
            nonlocal delivered
            if delivered:return await receive()
            delivered=True;return {'type':'http.request','body':bytes(raw),'more_body':False}
        return await self.app(scope,replay,send)
def install_handlers(app):
    app.add_middleware(BoundedJSONBody)
    @app.exception_handler(RequestValidationError)
    async def invalid(request,exc):return error('invalid_request',422)
    @app.exception_handler(Exception)
    async def unexpected(request,exc):return error('internal_error',500)
