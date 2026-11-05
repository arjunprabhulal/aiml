"""Bounded documentation search handles and receipt-bound passage reads."""
import copy
import hashlib
import json
from pathlib import Path
import re
from bm25 import LexicalIndex
from version_documents import validate_snapshot,canonical_hash

SNAPSHOT_SHA256='56bbeff06b0349186c3e5999d2b4fe634c6355f3bc267d6e07c47bf2d5e32b19'

class ToolError(ValueError):pass

def load_snapshot(root=None):
    path=(root or Path(__file__).parent/'fixtures')/'snapshot.json'
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SNAPSHOT_SHA256:raise ToolError('snapshot_file_hash_mismatch')
    snapshot=json.loads(raw);validate_snapshot(snapshot);return snapshot

class DocumentationTools:
    def __init__(self,snapshot):
        validate_snapshot(snapshot)
        self.snapshot=copy.deepcopy(snapshot);self.corpus_id=snapshot['snapshot_id'];self.rows={};self.receipts={};self.closed=False
        for source in self.snapshot['documents']:
            for chunk in source['chunks']:
                self.rows[chunk['chunk_id']]={'passage_id':chunk['chunk_id'],'source_id':source['source_id'],'version':source['version'],'document_revision':source['document_revision'],'source_sha256':source['sha256'],'start_line':chunk['start_line'],'end_line':chunk['end_line'],'text_sha256':chunk['text_sha256'],'byte_count':len(chunk['text'].encode('utf-8')),'text':chunk['text'],'url':source['url']}
        if not self.rows or len(self.rows)>100:raise ToolError('unsupported_corpus_size')
        self.index=LexicalIndex(self.snapshot)
    def close(self):
        if not self.closed:self.index.close();self.closed=True
    def available(self):
        if self.closed:raise ToolError('tools_closed')
    def search(self,query,k=2,version='3.12'):
        self.available()
        if type(k) is not int or not 1<=k<=10:raise ToolError('invalid_k')
        if not isinstance(query,str) or re.fullmatch(r'[A-Za-z0-9]{1,64}',query) is None:raise ToolError('invalid_query')
        if not isinstance(version,str) or re.fullmatch(r'[0-9]+\.[0-9]+',version) is None:raise ToolError('invalid_version')
        query=query.lower()
        request={'corpus_id':self.corpus_id,'query':query,'version':version,'k':k}
        request_id=canonical_hash(request)
        # Corpus is capped at 100. Fetch all native ranks, then version-filter
        # before applying the caller's k, without losing eligible candidates.
        ranked=self.index.search(query,limit=100)['results']
        eligible=[row for row in ranked if row['version']==version][:k]
        handles=[]
        for rank,row in enumerate(eligible,1):
            source=self.rows[row['chunk_id']]
            handle={'corpus_id':self.corpus_id,'search_request_id':request_id,**{key:value for key,value in source.items() if key not in ('text','url')},'native_score':row['native_score'],'rank':rank}
            handle['read_token']=canonical_hash(handle);handles.append(handle)
        result={'corpus_id':self.corpus_id,'search_request_id':request_id,'query':query,'version':version,'k':k,'results':handles}
        self.receipts[request_id]=copy.deepcopy(result)
        return copy.deepcopy(result)
    def validate_handle(self,handle):
        self.available()
        if not isinstance(handle,dict):raise ToolError('invalid_read_handle')
        if handle.get('corpus_id')!=self.corpus_id:raise ToolError('stale_corpus')
        passage=handle.get('passage_id')
        if not isinstance(passage,str) or passage not in self.rows:raise ToolError('unknown_passage')
        request=handle.get('search_request_id')
        if not isinstance(request,str) or request not in self.receipts:raise ToolError('unissued_search_receipt')
        expected=next((row for row in self.receipts[request]['results'] if row['passage_id']==passage),None)
        try:equal=expected is not None and canonical_hash(handle)==canonical_hash(expected)
        except (ValueError,TypeError,OverflowError):equal=False
        if not equal:raise ToolError('invalid_read_handle')
        return copy.deepcopy(expected)
    def read_cost(self,handle):return self.validate_handle(handle)['byte_count']
    def _read_payload(self,handle):
        handle=self.validate_handle(handle);source=self.rows[handle['passage_id']]
        body={**handle,'text':source['text'],'url':source['url'],'read_request_id':canonical_hash({'search_request_id':handle['search_request_id'],'read_token':handle['read_token']})}
        return {**body,'result_sha256':canonical_hash(body)}
    def read(self,handle):return self._read_payload(handle)
    def validate_read(self,result,handle):
        expected=self._read_payload(handle)
        try:equal=canonical_hash(result)==canonical_hash(expected)
        except (ValueError,TypeError,OverflowError):equal=False
        if not equal:raise ToolError('invalid_read_result')
        return copy.deepcopy(expected)
