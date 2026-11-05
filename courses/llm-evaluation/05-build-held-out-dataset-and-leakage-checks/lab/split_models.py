"""Typed tracker cases; derived from the course's existing Pydantic case schema."""
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Expected(BaseModel):
    model_config=ConfigDict(extra='forbid')
    label:Literal['bug','feature','docs','question']
    priority:Literal['p0','p1','p2']|None=None

class SplitCase(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[a-z0-9-]+$')
    issue:str=Field(min_length=1)
    expected:Expected
    must_mention:list[str]=[]
    source_id:str|None=None
    split:Literal['development','held_out']
    @field_validator('issue')
    @classmethod
    def nonblank(cls,value):
        if not any(c.isalnum() for c in value):raise ValueError('issue must contain letters or digits')
        return value

class SplitDataset(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str
    version:int
    cases:list[SplitCase]=Field(min_length=1)
    @model_validator(mode='after')
    def valid_sources(self):
        by_id={c.id:c for c in self.cases}
        if len(by_id)!=len(self.cases):raise ValueError('duplicate case ID')
        for c in self.cases:
            if c.source_id is not None:
                parent=by_id.get(c.source_id)
                if parent is None or parent.source_id is not None:
                    raise ValueError('source_id must name an original case')
        return self

class FrozenSplit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version:Literal[1]=1
    dataset_name:str
    held_out:dict[str,str]

def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))

def case_hash(case:SplitCase):
    return hashlib.sha256(canonical(case.model_dump()).encode()).hexdigest()

def freeze(dataset:SplitDataset):
    return FrozenSplit(dataset_name=dataset.name,held_out={c.id:case_hash(c) for c in dataset.cases if c.split=='held_out'})
