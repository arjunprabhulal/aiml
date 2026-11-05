"""Deterministic source-bound chunks for an explicitly synthetic developer API."""
import hashlib
import json
import re
from load_documents import IngestionError, load_documents

CONFIGS={
 'fixed-char':{'strategy':'fixed-char','version':1,'max_chars':80},
 'paragraph':{'strategy':'paragraph','version':1,'max_chars':None},
 'heading-aware':{'strategy':'heading-aware','version':1,'max_chars':220},
}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()

def sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()

def config_checked(config):
    try:
        supported=isinstance(config,dict) and any(digest(config)==digest(c) for c in CONFIGS.values())
    except (TypeError,ValueError,OverflowError):
        supported=False
    if not supported:raise IngestionError('unsupported_chunk_config')
    return dict(config)

def sections(document):
    text=document['text'];headings=list(re.finditer(r'^#{1,6} (.+)(?:\n|$)',text,re.MULTILINE))
    if not headings or headings[0].start()!=0:raise IngestionError('heading_required')
    for position,heading in enumerate(headings):
        start=heading.end();end=headings[position+1].start() if position+1<len(headings) else len(text)
        if text[start:end].strip():
            yield {'section_id':digest({'document_revision':document['document_revision'],'heading_start':heading.start()}),'section_title':heading.group(1),'start':start,'end':end}

def paragraph_spans(text,start,end):
    spans=[];cursor=start;begin=None;last=None
    for line in text[start:end].splitlines(keepends=True):
        if line.strip():
            if begin is None:begin=cursor
            last=cursor+len(line)
        elif begin is not None:
            spans.append((begin,last));begin=None
        cursor+=len(line)
    if begin is not None:spans.append((begin,last))
    return spans

def chunks_for(document,config):
    text=document['text'];output=[]
    for section in sections(document):
        paragraphs=paragraph_spans(text,section['start'],section['end'])
        if config['strategy']=='fixed-char':
            spans=[(start,min(start+config['max_chars'],section['end'])) for start in range(section['start'],section['end'],config['max_chars']) if text[start:min(start+config['max_chars'],section['end'])].strip()]
        elif config['strategy']=='paragraph':spans=paragraphs
        else:
            spans=[]
            for start,end in paragraphs:
                if spans and end-spans[-1][0]<=config['max_chars']:
                    spans[-1]=(spans[-1][0],end)
                else:spans.append((start,end))
        for start,end in spans:
            content=text[start:end]
            payload={'source_id':document['source_id'],'version':document['version'],'document_revision':document['document_revision'],'section_id':section['section_id'],'section_title':section['section_title'],'order':len(output),'start':start,'end':end,'start_line':text.count('\n',0,start)+1,'end_line':text.count('\n',0,end-1)+1,'text':content,'text_sha256':sha(content)}
            output.append({'chunk_id':digest({'config':config,**payload}),**payload})
    return output

def index_from_documents(documents,config):
    config=config_checked(config)
    documents=sorted(documents,key=lambda d:d['source_id'])
    chunks=[chunk for document in documents for chunk in chunks_for(document,config)]
    body={'schema_version':1,'execution_mode':'offline-synthetic-source-processing','config':config,'documents':documents,'chunks':chunks}
    return {**body,'index_id':digest(body)}

def build_index(manifest,config=None):
    documents=[]
    for source in load_documents(manifest)['documents']:
        if any(not isinstance(source.get(key),str) or not source[key] for key in ('source_id','version','path','title','sha256','url','fact_status')) or re.fullmatch(r'[0-9]+\.[0-9]+',source['version']) is None:
            raise IngestionError('invalid_source_metadata')
        source={**source,'normalized_text_sha256':sha(source['text'])}
        identity={key:value for key,value in source.items() if key!='text'}
        documents.append({**source,'document_revision':digest(identity)})
    return index_from_documents(documents,CONFIGS['paragraph'] if config is None else config)

def validate_index(index):
    try:
        if not isinstance(index,dict) or type(index.get('schema_version')) is not int or index['schema_version']!=1:raise ValueError()
        if index.get('execution_mode')!='offline-synthetic-source-processing':raise ValueError()
        config=config_checked(index['config']);documents=index['documents']
        if not isinstance(documents,list) or not documents:raise ValueError()
        seen=set();paths=set()
        for doc in documents:
            if not isinstance(doc,dict) or any(not isinstance(doc.get(key),str) or not doc[key] for key in ('source_id','version','path','title','sha256','text','url','fact_status','document_revision')):raise ValueError()
            if re.fullmatch(r'[0-9]+\.[0-9]+',doc['version']) is None:raise ValueError()
            if doc['source_id'] in seen or doc['path'] in paths:raise ValueError()
            seen.add(doc['source_id']);paths.add(doc['path'])
            if len(doc['text'].encode('utf-8'))>65536 or not doc['text'].strip() or '\x00' in doc['text'] or '\r\n' in doc['text']:raise ValueError()
            if re.fullmatch('[0-9a-f]{64}',doc['sha256']) is None:raise ValueError()
            if doc.get('normalized_text_sha256')!=sha(doc['text']):raise ValueError()
            if doc['document_revision']!=digest({key:value for key,value in doc.items() if key not in ('text','document_revision')}):raise ValueError()
        if digest(index)!=digest(index_from_documents(documents,config)):raise ValueError()
    except (ValueError,KeyError,TypeError,UnicodeError,OverflowError) as error:
        raise IngestionError('invalid_chunk_index') from error
    return index
