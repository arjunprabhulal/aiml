"""Fixed-development lexical evaluation across an explicitly synthetic corpus update."""
import copy
import hashlib
import json
import math
from pathlib import Path
from evaluation_bindings import bind_targets,metrics
from lexical import QuestionLexicalRetriever,question_terms
from version_documents import canonical_hash,validate_snapshot

CONFIG={'retriever':'sqlite-fts5-bm25','tokenizer':'module6-ascii-quoted-or-v1','candidate_budget':3,'cutoffs':[1,2]}
CASE_IDS={'utf8-write','replace-file','json-result-type','backup-schedule'}
PROVENANCE_SHA256='96d9cb5db4165b6e4d61408d20b3f1a6c935af51d83f1c54646e3f1ca407c7fe'

def checked_cases(cases):
    if not isinstance(cases,list) or len(cases)!=4 or any(not isinstance(c,dict) or not isinstance(c.get('id'),str) for c in cases):raise ValueError('fixed_development_cases_required')
    if {c['id'] for c in cases}!=CASE_IDS:raise ValueError('fixed_development_cases_required')
    for case in cases:
        if case.get('split')!='development' or case.get('class') not in ('answerable','unsupported'):raise ValueError('development_only')
        if not isinstance(case.get('input'),str) or not isinstance(case.get('tags'),dict):raise ValueError('invalid_case')
        if not isinstance(case.get('expected'),dict):raise ValueError('invalid_target_class')
        targets=case['expected'].get('targets')
        if not isinstance(targets,list) or (case['class']=='answerable')!=bool(targets):raise ValueError('invalid_target_class')
    return cases

def requests_from_cases(cases):
    return [{'case_id':c['id'],'query':c['input'],'version':c['tags']['python_version']} for c in checked_cases(cases)]

def load_inputs(root=None):
    root=Path(root) if root is not None else Path(__file__).parent/'fixtures'
    raw=(root/'provenance.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PROVENANCE_SHA256:raise ValueError('provenance_hash_mismatch')
    provenance=json.loads(raw)
    for relative,expected in provenance['fixture_sha256'].items():
        path=Path(relative)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='fixtures':raise ValueError('invalid_fixture_path')
        if hashlib.sha256((root/Path(*path.parts[1:])).read_bytes()).hexdigest()!=expected:raise ValueError('fixture_hash_mismatch')
    before=json.loads((root/'baseline-snapshot.json').read_text());after=json.loads((root/'updated-snapshot.json').read_text())
    validate_snapshot(before);validate_snapshot(after)
    return before,after,checked_cases(json.loads((root/'development-cases.json').read_text())),json.loads((root/'reannotations.json').read_text())

def _config(config):
    try:equal=canonical_hash(config)==canonical_hash(CONFIG)
    except (TypeError,ValueError,OverflowError) as error:raise ValueError('unsupported_config') from error
    if not equal:raise ValueError('unsupported_config')
    return copy.deepcopy(config)

def _requests(requests):
    if not isinstance(requests,list) or len(requests)!=4:raise ValueError('fixed_requests_required')
    if any(not isinstance(r,dict) or not isinstance(r.get('case_id'),str) for r in requests):raise ValueError('case_join_mismatch')
    if {r['case_id'] for r in requests}!=CASE_IDS:raise ValueError('case_join_mismatch')
    for row in requests:
        if not isinstance(row,dict) or set(row)!={'case_id','query','version'}:raise ValueError('labels_not_retrieval_inputs')
        question_terms(row['query'])
        if not isinstance(row['version'],str):raise ValueError('invalid_version')
    return copy.deepcopy(requests)

def run_rankings(snapshot,requests,config=None):
    validate_snapshot(snapshot);requests=_requests(requests);config=_config(CONFIG if config is None else config)
    if sum(len(d['chunks']) for d in snapshot['documents'])>100:raise ValueError('corpus_bound')
    retriever=QuestionLexicalRetriever(snapshot);rows=[]
    try:
        for request in requests:
            ranked=retriever.search(request['query'],k=config['candidate_budget'],policy={'version':{'$eq':request['version']}})
            rows.append({'case_id':request['case_id'],'query_terms':question_terms(request['query']),'ranked':ranked})
    finally:retriever.close()
    body={'snapshot_id':snapshot['snapshot_id'],'requests':requests,'request_sha256':canonical_hash(requests),'config':config,'config_sha256':canonical_hash(config),'rows':rows}
    return {**body,'run_sha256':canonical_hash(body)}

def validate_run(snapshot,run):
    validate_snapshot(snapshot)
    try:
        _requests(run['requests']);_config(run['config'])
        if run['snapshot_id']!=snapshot['snapshot_id'] or run['request_sha256']!=canonical_hash(run['requests']) or run['config_sha256']!=canonical_hash(run['config']):raise ValueError()
        if run['run_sha256']!=canonical_hash({k:v for k,v in run.items() if k!='run_sha256'}):raise ValueError()
        expected={r['case_id']:r for r in run['requests']};rows=run['rows']
        if not isinstance(rows,list) or len(rows)!=len(expected) or {r['case_id'] for r in rows}!=set(expected):raise ValueError()
        chunks={c['chunk_id']:{'chunk_id':c['chunk_id'],'source_id':d['source_id'],'version':d['version'],'url':d['url'],'text':c['text']} for d in snapshot['documents'] for c in d['chunks']}
        for row in rows:
            request=expected[row['case_id']]
            if row['query_terms']!=question_terms(request['query']) or len(row['ranked'])>run['config']['candidate_budget']:raise ValueError()
            seen=set()
            for item in row['ranked']:
                if item['chunk_id'] in seen or item['chunk_id'] not in chunks or item['version']!=request['version']:raise ValueError()
                seen.add(item['chunk_id'])
                if any(item.get(k)!=v for k,v in chunks[item['chunk_id']].items()) or type(item['native_score']) not in (int,float) or not math.isfinite(item['native_score']):raise ValueError()
        # This deterministic local retriever can rederive scores/order/completeness.
        # A self-hash alone would accept a consistently rehashed forged ranking.
        if canonical_hash(rows)!=canonical_hash(run_rankings(snapshot,run['requests'],run['config'])['rows']):raise ValueError()
    except (KeyError,TypeError,ValueError,OverflowError) as exc:raise ValueError('invalid_run_binding') from exc
    return run

def reannotate(before,after,cases,annotations):
    """Trusted local operator decisions, checked against both exact snapshots.

    This checks consistency, not author identity, factual validity or permission.
    A deleted source cannot be made supported by silently selecting another source.
    """
    checked_cases(cases);bind_targets(before,cases);validate_snapshot(after)
    revised=copy.deepcopy(cases);by_id={c['id']:c for c in revised};receipts=[];seen=set()
    if not isinstance(annotations,list):raise ValueError('invalid_reannotations')
    for annotation in annotations:
        try:
            if set(annotation)!={'case_id','old_snapshot_id','new_snapshot_id','old_target','new_target','reason'}:raise ValueError()
            cid=annotation['case_id']
            if cid in seen or cid not in by_id:raise ValueError()
            seen.add(cid);case=by_id[cid]
            if annotation['old_snapshot_id']!=before['snapshot_id'] or annotation['new_snapshot_id']!=after['snapshot_id']:raise ValueError()
            old,new=annotation['old_target'],annotation['new_target']
            if len(case['expected']['targets'])!=1 or canonical_hash(old)!=canonical_hash(case['expected']['targets'][0]):raise ValueError()
            if new['source_id']!=old['source_id'] or new['source_version']!=old['source_version']:raise ValueError()
            if not isinstance(annotation['reason'],str) or not annotation['reason'].strip() or len(annotation['reason'])>1024:raise ValueError()
            candidate=copy.deepcopy(case);candidate['expected']['targets']=[copy.deepcopy(new)]
            bound,_=bind_targets(after,[candidate])
            if bound[cid]['target_chunk_ids']!=[new['chunk_id']]:raise ValueError()
            case['expected']['targets']=[copy.deepcopy(new)]
            receipt={**copy.deepcopy(annotation),'new_current_chunk_ids':bound[cid]['target_chunk_ids'],'old_target_sha256':canonical_hash(old),'new_target_sha256':canonical_hash(new)}
            receipts.append({**receipt,'receipt_sha256':canonical_hash(receipt)})
        except (KeyError,TypeError,ValueError) as exc:raise ValueError('invalid_reannotation') from exc
    return revised,receipts

def _score(snapshot,run,cases):
    by_id={r['case_id']:r['ranked'] for r in run['rows']};result=[]
    for case in cases:
        try:bindings,_=bind_targets(snapshot,[case])
        except ValueError:
            source_ids={d['source_id'] for d in snapshot['documents']}
            missing=any(t['source_id'] not in source_ids for t in case['expected']['targets'])
            result.append({'case_id':case['id'],'status':'not-comparable','reason':'deleted_target_source' if missing else 'stale_target_binding','metrics':None});continue
        targets=bindings[case['id']]['target_chunk_ids']
        result.append({'case_id':case['id'],'status':'supported' if targets else 'unsupported-excluded','target_chunk_ids':targets,'returned_count':len(by_id[case['id']]),'metrics':{str(k):{**metrics(by_id[case['id']],targets,k),'target_count':len(targets),'miss':not any(r['chunk_id'] in targets for r in by_id[case['id']][:k]) if targets else None} for k in CONFIG['cutoffs']}})
    return result

def compare_runs(before,after,before_run,after_run,cases,annotations):
    validate_run(before,before_run);validate_run(after,after_run);checked_cases(cases)
    if canonical_hash(before_run['requests'])!=canonical_hash(after_run['requests']) or canonical_hash(before_run['config'])!=canonical_hash(after_run['config']):raise ValueError('comparison_context_mismatch')
    if canonical_hash(before_run['requests'])!=canonical_hash(requests_from_cases(cases)):raise ValueError('case_request_mismatch')
    bind_targets(before,cases)
    stale=_score(after,after_run,cases);revised,receipts=reannotate(before,after,cases,annotations)
    previous=_score(before,before_run,cases);current=_score(after,after_run,revised);current_by={r['case_id']:r for r in current};paired=[]
    for old in previous:
        new=current_by[old['case_id']]
        row={'case_id':old['case_id'],'before':old,'after':new,'comparison':'paired-supported' if old['status']==new['status']=='supported' else 'not-comparable' if new['status']=='not-comparable' else 'unsupported-excluded'}
        if row['comparison']=='paired-supported':row['recall_delta']={str(k):new['metrics'][str(k)]['recall_at_k']-old['metrics'][str(k)]['recall_at_k'] for k in CONFIG['cutoffs']}
        paired.append(row)
    paired_supported=[r for r in paired if r['comparison']=='paired-supported'];aggregate={}
    for k in CONFIG['cutoffs']:
        aggregate[str(k)]={'paired_supported_denominator':len(paired_supported),'before_mean_recall':math.fsum(r['before']['metrics'][str(k)]['recall_at_k'] for r in paired_supported)/len(paired_supported) if paired_supported else None,'after_mean_recall':math.fsum(r['after']['metrics'][str(k)]['recall_at_k'] for r in paired_supported)/len(paired_supported) if paired_supported else None}
    return {'same_request_sha256':before_run['request_sha256'],'same_config_sha256':before_run['config_sha256'],'stale_binding_attempt':stale,'reannotation_receipts':receipts,'per_case':paired,'paired_aggregate':aggregate,'not_comparable_cases':[r['case_id'] for r in paired if r['comparison']=='not-comparable'],'unsupported_cases':[r['case_id'] for r in paired if r['comparison']=='unsupported-excluded']}
