"""Local HTTP tracing, no hosted collector and no generation."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from http_contract import BoundedJSONBody,error_body
from service import RetrieveRequest
from tools import load_snapshot,DocumentationTools
from recorder import Recorder
from traced import traced_retrieve

def create_app(tool_factory=DocumentationTools,recorder=None):
    recorder=recorder or Recorder()
    @asynccontextmanager
    async def lifespan(app):
        app.state.snapshot=load_snapshot()
        try:yield
        finally:app.state.snapshot=None
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None);app.state.recorder=recorder
    app.add_middleware(BoundedJSONBody)
    @app.exception_handler(RequestValidationError)
    async def invalid(request,error):return JSONResponse(error_body('invalid_request'),422)
    @app.get('/health')
    async def health():return {'status':'ok','corpus_id':app.state.snapshot['snapshot_id']}
    @app.get('/traces')
    async def traces():return {'traces':recorder.snapshot(),'retention':recorder.stats()}
    @app.post('/retrieve')
    async def endpoint(payload:RetrieveRequest):
        with recorder.request() as trace_id:
            with recorder.span('admission'):pass
            try:code,body=await asyncio.to_thread(traced_retrieve,payload,app.state.snapshot,recorder,tool_factory)
            except Exception:
                with recorder.span('error'):pass
                code,body=500,error_body('internal_error')
            recorder.mark_response(code)
            response=JSONResponse(body,code);response.headers['X-Execution-Trace-ID']=trace_id
            return response
    return app
app=create_app()
