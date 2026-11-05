"""Frozen tiny-development comparison; label joins occur after retrieval."""
import hashlib
import math
from hybrid import HybridRetriever
from rerank import rerank
from version_documents import validate_snapshot

CANDIDATE_BUDGET=3
RANK_CONSTANT=60
CUTOFFS=(1,2)
CONFIGURATIONS=('lexical','vector','rrf','rrf+coverage')


def retrieve_runs(snapshot,embeddings,questions):
    """questions contains only id, query and requested version; no target labels."""
    retriever=HybridRetriever(snapshot,embeddings);runs=[]
    try:
        for question in questions:
            policy={'version':{'$eq':question['version']}}
            hybrid=retriever.search(question['query'],k=CANDIDATE_BUDGET,candidate_budget=CANDIDATE_BUDGET,rank_constant=RANK_CONSTANT,policy=policy)
            runs.append({'case_id':question['case_id'],'query':question['query'],'version':question['version'],'lexical_query_terms':hybrid['lexical_query_terms'],'rankings':{'lexical':hybrid['lexical'],'vector':hybrid['vector'],'rrf':hybrid['results'],'rrf+coverage':rerank(question['query'],hybrid['results'],snapshot,k=CANDIDATE_BUDGET)}})
    finally:retriever.close()
    return runs


def bind_targets(snapshot,cases):
    """Map legacy labels by source ID, API version and exact chunk-text hash."""
    validate_snapshot(snapshot)
    bindings={};receipts=[]
    for case in cases:
        if case['id'] in bindings:raise ValueError('duplicate_case')
        if case['split']!='development':raise ValueError('development_only')
        targets=[]
        for target in case['expected']['targets']:
            matches=[chunk for source in snapshot['documents'] if source['source_id']==target['source_id'] and source['version']==target['source_version'] and source['sha256']==target['source_text_sha256'] for chunk in source['chunks'] if hashlib.sha256(chunk['text'].encode('utf-8')).hexdigest()==target['chunk_text_sha256']]
            if len(matches)!=1:raise ValueError('target_binding_not_bijective')
            cid=matches[0]['chunk_id']
            if cid in targets:raise ValueError('duplicate_target')
            targets.append(cid)
            receipts.append({'case_id':case['id'],'legacy_chunk_id':target['chunk_id'],'current_chunk_id':cid,'binding':['source_id','source_version','source_text_sha256','chunk_text_sha256']})
        if case['class']=='answerable' and not targets:raise ValueError('answerable_requires_targets')
        if case['class']!='answerable' and targets:raise ValueError('unsupported_must_have_no_targets')
        bindings[case['id']]={'case_class':case['class'],'target_chunk_ids':targets}
    return bindings,receipts


def metrics(rows,targets,k):
    ids=[r['chunk_id'] for r in rows]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate_ranked_chunk')
    ranks=[i for i,cid in enumerate(ids,1) if cid in targets]
    if not targets:return {'target_ranks':[],'recall_at_k':None,'reciprocal_rank_at_k':None,'status':'unsupported-excluded'}
    within=[r for r in ranks if r<=k]
    return {'target_ranks':ranks,'recall_at_k':len(within)/len(targets),'reciprocal_rank_at_k':1/min(within) if within else 0.0,'status':'supported'}


def evaluate(runs,bindings):
    if len({r['case_id'] for r in runs})!=len(runs) or set(bindings)!={r['case_id'] for r in runs}:raise ValueError('case_join_mismatch')
    per_query=[]
    for run in runs:
        label=bindings[run['case_id']]
        per_query.append({'case_id':run['case_id'],'case_class':label['case_class'],'target_chunk_ids':label['target_chunk_ids'],'configurations':{name:{str(k):metrics(run['rankings'][name],label['target_chunk_ids'],k) for k in CUTOFFS} for name in CONFIGURATIONS}})
    supported=[r for r in per_query if r['case_class']=='answerable']
    aggregate={name:{str(k):{'supported_case_count':len(supported),'mean_recall_at_k':math.fsum(r['configurations'][name][str(k)]['recall_at_k'] for r in supported)/len(supported) if supported else None,'mean_reciprocal_rank_at_k':math.fsum(r['configurations'][name][str(k)]['reciprocal_rank_at_k'] for r in supported)/len(supported) if supported else None} for k in CUTOFFS} for name in CONFIGURATIONS}
    unsupported=[{'case_id':run['case_id'],'returned_candidate_counts':{name:len(rows) for name,rows in run['rankings'].items()}} for run in runs if bindings[run['case_id']]['case_class']!='answerable']
    misses={name:{str(k):[r['case_id'] for r in supported if r['configurations'][name][str(k)]['recall_at_k']==0] for k in CUTOFFS} for name in CONFIGURATIONS}
    return {'supported_misses':misses,'per_query':per_query,'aggregate':aggregate,'unsupported_candidate_behavior':unsupported,'supported_case_count':len(supported),'unsupported_case_count':len(unsupported)}
