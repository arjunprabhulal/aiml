"""Verbatim Module 6 label binding and metric functions; stdlib imports only."""
import hashlib
from version_documents import validate_snapshot

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

