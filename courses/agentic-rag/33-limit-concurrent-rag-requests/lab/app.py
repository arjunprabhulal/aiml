"""Process-local HTTP admission before worker-local SQLite retrieval."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from http_contract import BoundedJSONBody,error_body
from service import RetrieveRequest,retrieve
from tools import load_snapshot,DocumentationTools
from gate import Gate,Refused,finish_worker

def create_app(tool_factory=DocumentationTools,max_active=1,max_waiting=1,wait_seconds=0.15):
    gate=Gate(max_active,max_waiting,wait_seconds)
    @asynccontextmanager
    async def lifespan(app):
        app.state.snapshot=load_snapshot()
        try:yield
        finally:app.state.snapshot=None
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None);app.state.gate=gate
    app.add_middleware(BoundedJSONBody)
    @app.exception_handler(RequestValidationError)
    async def invalid(request,error):return JSONResponse(error_body('invalid_request'),422)
    @app.get('/health')
    async def health():return {'status':'ok','gate':gate.snapshot()}
    @app.post('/retrieve')
    async def endpoint(payload:RetrieveRequest):
        try:
            async with gate.lease():
                try:code,body=await finish_worker(retrieve,payload,app.state.snapshot,tool_factory)
                except Exception:code,body=500,error_body('internal_error')
                return JSONResponse(body,code)
        except Refused as error:return JSONResponse(error_body(str(error)),429 if str(error)=='queue_full' else 503)
    return app
app=create_app()
