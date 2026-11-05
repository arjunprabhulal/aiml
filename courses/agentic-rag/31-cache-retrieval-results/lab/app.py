"""Cache materialized search/read results; no model or cached executable handles."""
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import FastAPI,Header
from pydantic import BaseModel,ConfigDict,Field,field_validator
from authorization import Authorization,AccessError
from cache import ResultCache
from http_support import install_handlers,error
from version_documents import canonical_hash

PIPELINE={'name':'literal-search-read','version':1,'max_passages':10}
class RetrieveRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    query:Annotated[str,Field(pattern=r'^[A-Za-z0-9]{1,64}$')]
    collection:Annotated[str,Field(min_length=1,max_length=32)]
    version:Annotated[str,Field(pattern=r'^[0-9]+\.[0-9]+$',max_length=16)]='3.12'
    k:Annotated[int,Field(ge=1,le=10)]=2
    @field_validator('query')
    @classmethod
    def normalize(cls,value):return value.lower()
def cache_key(engine,principal,request):
    return canonical_hash({'principal':principal,'policy_id':engine.policy_id,'corpus_id':engine.corpus_id,'request':request,'pipeline':PIPELINE})
def create_app(engine_factory=Authorization,cache_factory=ResultCache):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine=engine_factory();app.state.cache=cache_factory()
        try:yield
        finally:app.state.cache.clear();app.state.engine.issued.clear();app.state.engine=None
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None);install_handlers(app)
    @app.exception_handler(AccessError)
    async def denied(request,exc):return error(exc.code,exc.status)
    @app.get('/health')
    async def health():return {'status':'ok','corpus_id':app.state.engine.corpus_id,'policy_id':app.state.engine.policy_id,'cache_ttl_seconds':app.state.cache.ttl}
    @app.post('/retrieve')
    async def retrieve(payload:RetrieveRequest,authorization:Annotated[str|None,Header()]=None):
        engine=app.state.engine;principal=engine.resolve(authorization);request=payload.model_dump()
        engine.authorize(principal,request['collection'])
        key=cache_key(engine,principal,request);cached=app.state.cache.get(key)
        if cached is not None:return {'cache':'hit','cache_key':key,'result':cached}
        try:
            found=engine.search(principal,request)
            evidence=[]
            for handle in found['results']:
                read=engine.read(principal,handle)
                # Materialized source projection, deliberately no issued IDs or executable handles.
                evidence.append({k:read[k] for k in ('passage_id','source_id','version','document_revision','source_sha256','start_line','end_line','text_sha256','byte_count','text','url')})
            body={'status':'completed' if evidence else 'incomplete','principal':principal,'corpus_id':engine.corpus_id,'policy_id':engine.policy_id,'request':request,'pipeline':PIPELINE,'evidence':evidence}
            body['result_sha256']=canonical_hash(body)
            stored=app.state.cache.put(key,body)
            return {'cache':'miss' if stored else 'bypass','cache_key':key,'result':body}
        except AccessError:raise
        except Exception:return error('tool_failure',503)
    return app
app=create_app()
