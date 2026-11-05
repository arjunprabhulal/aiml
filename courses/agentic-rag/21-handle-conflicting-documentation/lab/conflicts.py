"""Gate explicit synthetic contract directives; not a general prose detector."""
import hashlib
import json
from pathlib import Path
import re
from load_documents import load_documents

VALUES={'existing_path':{'refuse','overwrite'},'close_required':{'yes','no'}}
DIRECTIVE=re.compile(r'@quill ([a-z_]+) ([a-z_]+)=([a-z_]+)')


class DirectiveError(ValueError):
    """Eligible source directives cannot satisfy the narrow parser contract."""


class GateError(ValueError):
    """The controlled request is invalid."""


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()


def claims_from_source(source):
    revision=digest({key:value for key,value in source.items() if key!='text'})
    claims={};offset=0
    for line_number,line in enumerate(source['text'].splitlines(keepends=True),1):
        quote=line.rstrip('\r\n')
        if '@quill' in quote or quote.lstrip().startswith('@'):
            match=DIRECTIVE.fullmatch(quote)
            if match is None:raise DirectiveError('malformed_directive')
            operation,key,value=match.groups()
            if operation!='create_copy':raise DirectiveError('unsupported_operation')
            if key not in VALUES:raise DirectiveError('unsupported_claim_key')
            if value not in VALUES[key]:raise DirectiveError('unknown_directive_value')
            if key in claims:raise DirectiveError('duplicate_directive')
            claims[key]={'source_id':source['source_id'],'version':source['version'],'path':source['path'],'url':source.get('url'),'source_sha256':source['sha256'],'document_revision':revision,'operation':operation,'claim_key':key,'value':value,'start_line':line_number,'end_line':line_number,'start':offset,'end':offset+len(quote),'quote':quote}
        offset+=len(line)
    return claims


def gate(manifest,candidate_ids,requested_version,claim_key='existing_path'):
    if not isinstance(candidate_ids,list) or any(not isinstance(sid,str) or not sid for sid in candidate_ids):raise GateError('invalid_candidate_ids')
    if len(set(candidate_ids))!=len(candidate_ids):raise GateError('duplicate_candidate')
    if not isinstance(requested_version,str) or re.fullmatch(r'[0-9]+\.[0-9]+',requested_version) is None:raise GateError('invalid_requested_version')
    if not isinstance(claim_key,str) or claim_key not in VALUES:raise GateError('unsupported_requested_claim')
    loaded=load_documents(Path(manifest));sources={s['source_id']:s for s in loaded['documents']}
    if any(sid not in sources for sid in candidate_ids):raise GateError('unknown_candidate')
    selected=[sources[sid] for sid in candidate_ids]
    if any(not isinstance(s.get('version'),str) or re.fullmatch(r'[0-9]+\.[0-9]+',s['version']) is None for s in selected):raise GateError('invalid_source_version')
    eligible=[s for s in selected if s['version']==requested_version]
    excluded=[s['source_id'] for s in selected if s['version']!=requested_version]
    base={'requested_version':requested_version,'claim_key':claim_key,'operation':'create_copy','candidate_ids':list(candidate_ids),'eligible_source_ids':[s['source_id'] for s in eligible],'excluded_wrong_version_ids':excluded,'answer_request':None}
    if not eligible:return {**base,'status':'not_in_docs','reason':'no_eligible_version','claims':[]}
    claims=[];missing=[]
    for source in eligible:
        parsed=claims_from_source(source)
        if claim_key not in parsed:missing.append(source['source_id'])
        else:claims.append(parsed[claim_key])
    if missing:return {**base,'status':'not_in_docs','reason':'requested_claim_missing','missing_claim_source_ids':missing,'claims':claims}
    if len({claim['value'] for claim in claims})>1:return {**base,'status':'conflict','reason':'same_version_directives_disagree','claims':claims}
    request={'messages':[{'role':'system','content':'Describe only the supplied explicit fictional API contract. Cite every supplied source ID. Do not invent an unsupported rule.'},{'role':'user','content':json.dumps({'requested_version':requested_version,'operation':'create_copy','claim_key':claim_key,'source_claims':claims},sort_keys=True)}]}
    return {**base,'status':'ready','reason':'eligible_directives_agree','agreed_value':claims[0]['value'],'claims':claims,'answer_request':request}
