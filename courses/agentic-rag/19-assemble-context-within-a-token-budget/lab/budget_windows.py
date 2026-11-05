"""Map verified surrounding-context windows to the existing whole-item assembler."""
import json
from assembler import assemble
from contracts import parse_request
from surround import validate_windows

INSTRUCTIONS='Answer the current question from supplied reference passages. Cite the passage ID. If the references do not answer it, say so.'


def make_request(index,windows,ranked_seed_ids,question,context_limit=1024,max_new_tokens=128,margin=32,instructions=INSTRUCTIONS):
    validate_windows(index,windows)
    if not isinstance(ranked_seed_ids,list) or ranked_seed_ids!=windows['seed_ids']:
        raise ValueError('seed_ranking_mismatch')
    documents={source['source_id']:source for source in index['documents']}
    evidence=[];receipts=[]
    for group in windows['groups']:
        ranks=group['seed_ranks']
        if not ranks:raise ValueError('window_missing_seed')
        priority=min(item['rank'] for item in ranks)
        source=documents[group['source_id']]
        metadata={'source_id':group['source_id'],'version':group['version'],'path':source['path'],'url':source.get('url'),'document_revision':group['document_revision'],'section_id':group['section_id'],'start':group['start'],'end':group['end']}
        evidence.append({'id':group['window_id'],'source':json.dumps(metadata,sort_keys=True,separators=(',',':')),'text':group['text'],'score':-float(priority)})
        receipts.append({'window_id':group['window_id'],'priority_seed_rank':priority,'metadata':metadata,'chunk_ids':group['chunk_ids'],'seed_ids':group['seed_ids'],'seed_ranks':ranks,'members':group['members']})
    request=parse_request({'instructions':instructions,'current':question,'evidence':evidence,'context_limit':context_limit,'max_new_tokens':max_new_tokens,'margin':margin,'fill_order':['evidence','history']})
    return request,receipts


def assemble_windows(index,windows,ranked_seed_ids,question,counter,**options):
    request,receipts=make_request(index,windows,ranked_seed_ids,question,**options)
    result=assemble(request,counter.count_request)
    recounted=counter.count_request(result['messages'],result['tools'])
    if recounted!=result['input_tokens']:raise ValueError('complete_request_count_mismatch')
    result.update({'window_receipts':receipts,'full_request_recount':recounted,'separate_text_counts':{'instructions':counter.count_text(request.instructions),'question':counter.count_text(request.current),'all_window_texts':sum(counter.count_text(p.text) for p in request.evidence),'kept_window_texts':sum(counter.count_text(p.text) for p in request.evidence if p.id in result['kept_evidence'])},'scope':'whole-window admission; complete serialized request includes source labels, wrappers, chat template and generation prefix'})
    return result
