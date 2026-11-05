"""Real loopback HTTP boundary; public fixture identities, no JWT authentication."""
from contextlib import asynccontextmanager
from typing import Annotated,Any
from fastapi import FastAPI,Header
from pydantic import BaseModel,ConfigDict,Field,field_validator
from authorization import Authorization,AccessError
from http_support import install_handlers,error

class SearchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    query:Annotated[str,Field(pattern=r'^[A-Za-z0-9]{1,64}$')]
    collection:Annotated[str,Field(min_length=1,max_length=32)]
    version:Annotated[str,Field(pattern=r'^[0-9]+\.[0-9]+$',max_length=16)]='3.12'
    k:Annotated[int,Field(ge=1,le=10)]=2
    @field_validator('query')
    @classmethod
    def normalize(cls,value):return value.lower()
class ReadRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    handle:dict[str,Any]

def create_app(engine_factory=Authorization):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine=engine_factory()
        try:yield
        finally:app.state.engine.issued.clear();app.state.engine=None
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None);install_handlers(app)
    @app.exception_handler(AccessError)
    async def denied(request,exc):return error(exc.code,exc.status)
    @app.get('/health')
    async def health():return {'status':'ok','corpus_id':app.state.engine.corpus_id,'policy_id':app.state.engine.policy_id}
    @app.post('/search')
    async def search(payload:SearchRequest,authorization:Annotated[str|None,Header()]=None):
        engine=app.state.engine;principal=engine.resolve(authorization)
        try:return engine.search(principal,payload.model_dump())
        except AccessError:raise
        except Exception:return error('tool_failure',503)
    @app.post('/read')
    async def read(payload:ReadRequest,authorization:Annotated[str|None,Header()]=None):
        engine=app.state.engine;principal=engine.resolve(authorization)
        try:return engine.read(principal,payload.handle)
        except AccessError:raise
        except Exception:return error('tool_failure',503)
    return app
app=create_app()
