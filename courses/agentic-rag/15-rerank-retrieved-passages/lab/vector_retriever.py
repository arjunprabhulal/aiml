"""Real LangChain store backed only by preserved model vectors; no inference."""
import hashlib
import json
import math
from pathlib import Path
import re
from version_documents import validate_snapshot
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

VECTORS_SHA256 = 'bbadb40c26e0241de36f09f6068354f7589b9ce1a38bb49ba6998be4ca3b25e6'
DIMENSION = 1024


def checked_vector(vector):
    if not isinstance(vector,list) or len(vector)!=DIMENSION:
        raise ValueError('invalid_vector_dimension')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in vector):
        raise ValueError('nonfinite_or_invalid_vector')
    norm=math.sqrt(math.fsum(v*v for v in vector))
    if not math.isfinite(norm) or norm<=0:
        raise ValueError('invalid_vector_norm')
    return list(vector)


class SavedEmbeddings(Embeddings):
    def __init__(self,recording,allowed_questions):
        self.documents={text:checked_vector(vector) for text,vector in recording['documents'].items()}
        self.questions={text:checked_vector(recording['questions'][text]) for text in allowed_questions}

    def embed_documents(self,texts):
        if any(text not in self.documents for text in texts):raise ValueError('unrecorded_document')
        return [list(self.documents[text]) for text in texts]

    def embed_query(self,text):
        if text not in self.questions:raise ValueError('unrecorded_development_query')
        return list(self.questions[text])


def load_inputs(root=None):
    root=root or Path(__file__).parent/'fixtures'
    raw=(root/'vectors.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=VECTORS_SHA256:raise ValueError('vector_recording_hash_mismatch')
    snapshot=json.loads((root/'snapshot.json').read_text())
    cases=json.loads((root/'development-cases.json').read_text())
    if len(cases)!=4 or any(c['split']!='development' for c in cases):raise ValueError('development_cases_required')
    return snapshot,SavedEmbeddings(json.loads(raw),[c['input'] for c in cases]),cases


def version_filter(policy):
    if policy is None or policy=={}:return None
    if not isinstance(policy,dict) or set(policy)!={'version'}:raise ValueError('unsupported_filter')
    operator=policy['version']
    if not isinstance(operator,dict) or set(operator)!={'$eq'}:raise ValueError('unsupported_filter_operator')
    version=operator['$eq']
    if not isinstance(version,str) or re.fullmatch(r'[0-9]+\.[0-9]+',version) is None:raise ValueError('invalid_filter_version')
    return version


def rows_from_snapshot(snapshot):
    validate_snapshot(snapshot)
    rows=[];seen=set()
    for source in snapshot['documents']:
        if not isinstance(source.get('version'),str) or re.fullmatch(r'[0-9]+\.[0-9]+',source['version']) is None:raise ValueError('invalid_source_version')
        for chunk in source['chunks']:
            if chunk['chunk_id'] in seen:raise ValueError('duplicate_chunk_id')
            seen.add(chunk['chunk_id'])
            rows.append({'chunk_id':chunk['chunk_id'],'source_id':source['source_id'],'version':source['version'],'url':source['url'],'text':chunk['text']})
    return rows


class VectorRetriever:
    def __init__(self,snapshot,embeddings):
        self.rows=rows_from_snapshot(snapshot)
        self.store=InMemoryVectorStore(embeddings)
        self.store.add_documents([Document(id=r['chunk_id'],page_content=r['text'],metadata={k:v for k,v in r.items() if k!='text'}) for r in self.rows],ids=[r['chunk_id'] for r in self.rows])

    def search(self,query,k=2,policy=None):
        if type(k) is not int or k<1:raise ValueError('invalid_k')
        version=version_filter(policy)
        selected=None if version is None else lambda doc:doc.metadata['version']==version
        matches=self.store.similarity_search_with_score(query,k=len(self.rows),filter=selected)
        matches=sorted(matches,key=lambda item:(-item[1],item[0].metadata["chunk_id"]))[:k]
        return [{**doc.metadata,'text':doc.page_content,'score':float(score)} for doc,score in matches]
