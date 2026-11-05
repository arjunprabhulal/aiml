"""Transparent candidate-only token coverage; no learned reranker or model call."""
import copy
import math
import re
from version_documents import validate_snapshot
from hybrid import question_terms


def query_tokens(query):
    return question_terms(query)


def rerank(query,candidates,snapshot,k=2):
    """Score exact supplied candidate texts, retaining incoming rank for ties."""
    if type(k) is not int or k<1:raise ValueError('invalid_k')
    tokens=query_tokens(query)
    validate_snapshot(snapshot)
    if not isinstance(candidates,list):raise ValueError('invalid_candidates')
    known={chunk['chunk_id']:{'source_id':source['source_id'],'version':source['version'],'url':source['url'],'text':chunk['text']} for source in snapshot['documents'] for chunk in source['chunks']}
    seen=set();ranked=[]
    for rank,row in enumerate(candidates,1):
        if not isinstance(row,dict) or not isinstance(row.get('chunk_id'),str) or not row['chunk_id'] or row['chunk_id'] not in known:raise ValueError('unknown_candidate')
        cid=row['chunk_id']
        if cid in seen:raise ValueError('duplicate_candidate')
        seen.add(cid)
        if any(row.get(key)!=value for key,value in known[cid].items()):raise ValueError('candidate_payload_mismatch')
        for key in ['lexical_rank','vector_rank']:
            value=row.get(key)
            if value is not None and (type(value) is not int or value<1):raise ValueError('invalid_candidate_rank')
        for key in ['lexical_score','vector_score','fused_score','lexical_contribution','vector_contribution']:
            value=row.get(key)
            if value is not None:
                try:valid=type(value) in (int,float) and math.isfinite(value)
                except OverflowError:valid=False
                if not valid:raise ValueError('invalid_candidate_score')
        passage_tokens=set(re.findall(r'[a-z0-9]+',row['text'].lower()))
        matched=sorted(set(tokens)&passage_tokens)
        ranked.append({**copy.deepcopy(row),'incoming_rank':rank,'rerank_features':{'query_tokens':tokens,'matched_tokens':matched,'matched_count':len(matched),'query_token_count':len(tokens)},'coverage_score':len(matched)/len(tokens)})
    ranked.sort(key=lambda row:(-row['coverage_score'],row['incoming_rank']))
    return [{**row,'rerank_rank':rank} for rank,row in enumerate(ranked[:k],1)]
