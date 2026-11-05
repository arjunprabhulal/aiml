"""Strict transport projections of the unchanged local retrieval receipts."""
from typing import Annotated
from pydantic import BaseModel,ConfigDict,Field

Digest=Annotated[str,Field(pattern=r'^[0-9a-f]{64}$',strict=True)]
Version=Annotated[str,Field(pattern=r'^[0-9]+\.[0-9]+$',strict=True,max_length=16)]
Query=Annotated[str,Field(pattern=r'^[A-Za-z0-9]{1,64}$',strict=True)]


class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class Handle(StrictModel):
    corpus_id:Digest
    search_request_id:Digest
    passage_id:Digest
    source_id:Annotated[str,Field(min_length=1,max_length=256)]
    version:Version
    document_revision:Digest
    source_sha256:Digest
    start_line:Annotated[int,Field(ge=1,le=65536)]
    end_line:Annotated[int,Field(ge=1,le=65536)]
    text_sha256:Digest
    byte_count:Annotated[int,Field(ge=0,le=65536)]
    native_score:Annotated[float,Field(allow_inf_nan=False)]
    rank:Annotated[int,Field(ge=1,le=10)]
    read_token:Digest


class SearchResult(StrictModel):
    corpus_id:Digest
    search_request_id:Digest
    query:Query
    version:Version
    k:Annotated[int,Field(ge=1,le=10)]
    results:Annotated[list[Handle],Field(max_length=10)]


class ReadResult(Handle):
    text:Annotated[str,Field(max_length=65536)]
    url:Annotated[str,Field(max_length=2048)]
    read_request_id:Digest
    result_sha256:Digest
