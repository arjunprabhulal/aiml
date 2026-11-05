"""Synthetic collection authorization, bounded issued handles, no identity claims."""
import copy
import hashlib
import json
import math
import secrets
import time
from collections import OrderedDict
from pathlib import Path
from tools import DocumentationTools, load_snapshot, ToolError
from version_documents import canonical_hash

class AccessError(ValueError):
    def __init__(self, code, status=403):self.code=code;self.status=status;super().__init__(code)

class Authorization:
    def __init__(self, snapshot=None, policy=None, tool_factory=DocumentationTools, *, clock=time.monotonic, max_handles=64, handle_ttl=60):
        self.snapshot=copy.deepcopy(snapshot if snapshot is not None else load_snapshot())
        self.policy=copy.deepcopy(policy if policy is not None else json.loads((Path(__file__).parent/'fixtures/policy.json').read_text()))
        ids={d['source_id'] for d in self.snapshot['documents']}
        if set(self.policy)!= {'schema_version','description','collections','tokens','grants'} or self.policy['schema_version']!=1:raise ValueError('invalid_policy')
        collections=self.policy['collections'];grants=self.policy['grants'];tokens=self.policy['tokens']
        if not collections or not grants or not tokens:raise ValueError('empty_policy')
        for name,sources in collections.items():
            if not isinstance(name,str) or not isinstance(sources,list) or not sources or len(set(sources))!=len(sources) or not set(sources)<=ids:raise ValueError('invalid_collection')
        for principal,allowed in grants.items():
            if not isinstance(principal,str) or not isinstance(allowed,list) or not set(allowed)<=set(collections):raise ValueError('invalid_grants')
        if any(not isinstance(t,str) or not t or p not in grants for t,p in tokens.items()):raise ValueError('invalid_tokens')
        if type(max_handles) is not int or not 1<=max_handles<=1024 or not isinstance(handle_ttl,(int,float)) or isinstance(handle_ttl,bool) or not math.isfinite(handle_ttl) or not 0<handle_ttl<=3600:raise ValueError('invalid_handle_limits')
        self.corpus_id=self.snapshot['snapshot_id'];self.tool_factory=tool_factory
        self.clock=clock;self.max_handles=max_handles;self.handle_ttl=handle_ttl;self.issued=OrderedDict();self.search_calls=0;self.read_calls=0
    @property
    def policy_id(self):return canonical_hash(self.policy)
    def resolve(self, authorization):
        if not isinstance(authorization,str) or not authorization.startswith('Bearer '):raise AccessError('unauthenticated',401)
        token=authorization[7:]
        if token not in self.policy['tokens']:raise AccessError('unauthenticated',401)
        return self.policy['tokens'][token]
    def authorize(self, principal, collection):
        if principal not in self.policy['grants']:raise AccessError('unauthenticated',401)
        if not isinstance(collection,str) or collection not in self.policy['collections'] or collection not in self.policy['grants'][principal]:raise AccessError('collection_denied')
    def _prune(self):
        now=self.clock()
        for token,entry in list(self.issued.items()):
            if entry[0]<=now:del self.issued[token]
    def search(self, principal, request):
        self.authorize(principal,request['collection'])
        # Tool construction and invocation occur only after identity/grant checks.
        tools=self.tool_factory(self.snapshot)
        try:
            self.search_calls+=1
            ranked=tools.index.search(request['query'],limit=100)['results']
            eligible=[r for r in ranked if r['version']==request['version'] and r['source_id'] in self.policy['collections'][request['collection']]][:request['k']]
            request_id=canonical_hash({'principal':principal,'policy_id':self.policy_id,'corpus_id':self.corpus_id,'request':request})
            handles=[];self._prune()
            for rank,row in enumerate(eligible,1):
                source=tools.rows[row['chunk_id']]
                handle={'principal':principal,'collection':request['collection'],'policy_id':self.policy_id,'corpus_id':self.corpus_id,'search_request_id':request_id,'rank':rank,'native_score':row['native_score'],**{k:v for k,v in source.items() if k not in ('text','url')},'issued_id':secrets.token_hex(16)}
                self.issued[handle['issued_id']]=(self.clock()+self.handle_ttl,copy.deepcopy(handle),copy.deepcopy(source))
                while len(self.issued)>self.max_handles:self.issued.popitem(last=False)
                handles.append(handle)
            return {'principal':principal,'policy_id':self.policy_id,'corpus_id':self.corpus_id,'request':copy.deepcopy(request),'search_request_id':request_id,'results':copy.deepcopy(handles)}
        finally:tools.close()
    def read(self, principal, handle):
        if not isinstance(handle,dict):raise AccessError('invalid_handle')
        self.authorize(principal,handle.get('collection'))
        self._prune();entry=self.issued.get(handle.get('issued_id')) if isinstance(handle.get('issued_id'),str) else None
        if entry is None:raise AccessError('unissued_or_expired_handle')
        expected,source=entry[1:]
        try:equal=canonical_hash(handle)==canonical_hash(expected)
        except (TypeError,ValueError):equal=False
        if not equal or handle.get('principal')!=principal or handle.get('policy_id')!=self.policy_id or handle.get('corpus_id')!=self.corpus_id:raise AccessError('handle_binding_mismatch')
        if source['source_id'] not in self.policy['collections'][handle['collection']]:raise AccessError('collection_denied')
        self.read_calls+=1
        body={**copy.deepcopy(handle),'text':source['text'],'url':source['url']}
        return {**body,'result_sha256':canonical_hash(body)}
