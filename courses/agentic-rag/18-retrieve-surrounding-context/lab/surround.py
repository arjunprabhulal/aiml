"""Expand explicit seed IDs within one validated source revision and section."""
from chunk_index import digest, validate_index
from load_documents import IngestionError

def expand_context(index,seed_ids,radius=1):
    validate_index(index)
    if type(radius) is not int or not 0<=radius<=3:raise ValueError('invalid_radius')
    if not isinstance(seed_ids,list) or len(seed_ids)>100 or any(not isinstance(seed,str) or not seed for seed in seed_ids):raise ValueError('invalid_seeds')
    if len(set(seed_ids))!=len(seed_ids):raise ValueError('duplicate_seed')
    chunks={chunk['chunk_id']:chunk for chunk in index['chunks']}
    if any(seed not in chunks for seed in seed_ids):raise ValueError('unknown_or_stale_seed')
    ranks={seed:position+1 for position,seed in enumerate(seed_ids)}
    sections={}
    for chunk in index['chunks']:
        key=(chunk['source_id'],chunk['version'],chunk['document_revision'],chunk['section_id'])
        sections.setdefault(key,[]).append(chunk)
    requests={}
    for seed in seed_ids:
        chunk=chunks[seed];key=(chunk['source_id'],chunk['version'],chunk['document_revision'],chunk['section_id'])
        ordered=sections[key];position=next(i for i,c in enumerate(ordered) if c['chunk_id']==seed)
        requests.setdefault(key,[]).append((max(0,position-radius),min(len(ordered)-1,position+radius)))
    documents={doc['source_id']:doc for doc in index['documents']};groups=[]
    for key,windows in requests.items():
        merged=[]
        for start,end in sorted(windows):
            if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],end))
            else:merged.append((start,end))
        for start,end in merged:
            selected=sections[key][start:end+1];ids=[chunk['chunk_id'] for chunk in selected]
            present=sorted((seed for seed in ids if seed in ranks),key=ranks.get)
            body={'source_id':key[0],'version':key[1],'document_revision':key[2],'section_id':key[3],
                  'section_title':selected[0]['section_title'],'start_order':selected[0]['order'],'end_order':selected[-1]['order'],
                  'start':selected[0]['start'],'end':selected[-1]['end'],'chunk_ids':ids,'seed_ids':present,
                  'seed_ranks':[{'chunk_id':seed,'rank':ranks[seed]} for seed in present],
                  'members':[{'chunk_id':chunk,'role':'seed' if chunk in ranks else 'neighbor','retrieval_rank':ranks.get(chunk)} for chunk in ids],
                  'text':documents[key[0]]['text'][selected[0]['start']:selected[-1]['end']]}
            groups.append({'window_id':digest({'index_id':index['index_id'],**body}),**body})
    groups.sort(key=lambda group:(min(seed['rank'] for seed in group['seed_ranks']),group['source_id'],group['start_order'],group['window_id']))
    return {'schema_version':1,'execution_mode':'offline-explicit-seed-expansion','index_id':index['index_id'],'radius':radius,'seed_ids':list(seed_ids),'groups':groups}

def validate_windows(index,result):
    try:
        if not isinstance(result,dict):raise ValueError()
        expected=expand_context(index,result['seed_ids'],result['radius'])
        if digest(result)!=digest(expected):raise ValueError()
    except (ValueError,KeyError,TypeError,UnicodeError,OverflowError) as error:
        raise IngestionError('invalid_context_windows') from error
    return result
